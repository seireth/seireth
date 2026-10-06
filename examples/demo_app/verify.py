"""Create a saved Seireth demo project and verify real Docker assessments."""

import argparse
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.api.schemas import AssessmentEvidenceOut
from app.cli.verify import positive_timeout, require, wait_for_results

from .scenarios import COOKIE_SCENARIOS, IMAGE, ORIGIN, SCENARIOS


def validate_outcome(
    scenario, assessment_id, results, raw_evidence, plugins=("security-headers",)
):
    """Require exact findings, correctly associated evidence, and verified cleanup."""
    cookie_values = [
        value.split("=", 1)[1].split(";", 1)[0]
        for name, value in scenario.headers
        if name.lower() == "set-cookie"
    ]
    serialized = json.dumps((results, raw_evidence))
    if any(value and value in serialized for value in cookie_values):
        raise RuntimeError(f"{scenario.path}: cookie values were exposed")
    result = results.get("result") or {}
    if (
        results.get("assessment_id") != assessment_id
        or results.get("status") != "completed"
        or results.get("cleanup_pending") is not False
        or result.get("sandbox_backend") != "docker"
        or result.get("cleanup_verified") is not True
        or result.get("error")
    ):
        raise RuntimeError(
            f"{scenario.path}: assessment or Docker cleanup did not complete: {results}"
        )
    expected = {
        "security-headers": scenario.expected,
        "cookie-security": scenario.cookie_rules,
    }
    expected_count = sum(len(expected[plugin]) for plugin in plugins)
    findings = results["findings"]
    if (
        result.get("finding_count") != expected_count
        or result.get("plugins")
        != [
            {"id": plugin, "finding_count": len(expected[plugin])} for plugin in plugins
        ]
        or any(
            finding["plugin"] not in plugins or not finding["remediation"].strip()
            for finding in findings
        )
    ):
        raise RuntimeError(f"{scenario.path}: unexpected plugin summary or remediation")
    try:
        evidence = AssessmentEvidenceOut.model_validate(raw_evidence)
    except ValidationError:
        raise RuntimeError(f"{scenario.path}: API returned invalid evidence") from None
    finding_ids = [finding["id"] for finding in findings]
    if (
        evidence.assessment_id != assessment_id
        or evidence.status != "completed"
        or evidence.cleanup_pending
        or len(set(finding_ids)) != len(finding_ids)
        or Counter(entry.finding_id for entry in evidence.evidence)
        != Counter(finding_ids)
        or any(
            str(entry.data.url) != ORIGIN + scenario.path for entry in evidence.evidence
        )
    ):
        raise RuntimeError(
            f"{scenario.path}: findings/evidence do not match expected headers {scenario.expected}"
        )
    by_id = {finding["id"]: finding for finding in findings}
    for plugin in plugins:
        observed = Counter(
            entry.data.header if plugin == "security-headers" else entry.data.rule
            for entry in evidence.evidence
            if by_id[entry.finding_id]["plugin"] == plugin
        )
        if observed != Counter(expected[plugin]):
            raise RuntimeError(
                f"{scenario.path}: findings/evidence do not match {plugin} expectations"
            )
    return evidence.model_dump(mode="json")


def verify_resource_removal(assessment_id):
    """Independently query resources on the local daemon used by this demo."""
    selector = f"label=seireth.assessment={assessment_id}"
    for args in (
        ("ps", "-aq", "--filter", selector),
        ("network", "ls", "-q", "--filter", selector),
    ):
        output = subprocess.check_output(
            ["docker", *args], text=True, timeout=20
        ).strip()
        if output:
            raise RuntimeError(f"{assessment_id}: Docker resources remain: {output}")


def verify(
    base_url,
    *,
    scenarios=(*SCENARIOS, *COOKIE_SCENARIOS),
    timeout_seconds=120,
    project_name="Northstar Workspace | Plugin demo",
    register_only=False,
    check_resources=True,
):
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        runtime = require(client.get("/api/v1/runtime"), 200)
        if runtime["sandbox_backend"] != "docker":
            raise RuntimeError("Enable the Docker backend before registering the demo")
        project = require(
            client.post("/api/v1/projects", json={"name": project_name}), 200
        )
        report = {
            "project": project,
            "project_url": f"{base_url.rstrip('/')}/dashboard/projects/{project['id']}",
            "image": IMAGE,
            "cases": [],
        }
        target = require(
            client.post(
                "/api/v1/targets",
                json={
                    "project_id": project["id"],
                    "name": "Northstar Workspace",
                    "image": IMAGE,
                    "url": ORIGIN,
                },
            ),
            200,
        )
        report["target"] = target
        expected_actions = ["project.created", "target.registered"]
        cases = [
            (scenario, plugins)
            for scenario in scenarios
            for plugins in (
                (
                    ("security-headers",),
                    ("cookie-security",),
                    ("security-headers", "cookie-security"),
                )
                if scenario in COOKIE_SCENARIOS
                else (("security-headers",),)
            )
        ]
        for scenario, plugins in cases:
            case = {
                "path": scenario.path,
                "name": scenario.name,
                "expected_headers": list(scenario.expected),
                "target_id": target["id"],
                "url": ORIGIN + scenario.path,
                "plugins": list(plugins),
            }
            report["cases"].append(case)
            if register_only:
                continue
            print(
                f"Assessing {scenario.path} with {', '.join(plugins)}",
                file=sys.stderr,
                flush=True,
            )
            assessment = require(
                client.post(
                    "/api/v1/assessments",
                    json={
                        "project_id": project["id"],
                        "target_id": target["id"],
                        "url": ORIGIN + scenario.path,
                        "plugins": list(plugins),
                    },
                ),
                202,
            )
            results = wait_for_results(client, assessment["id"], timeout_seconds)
            evidence = validate_outcome(
                scenario,
                assessment["id"],
                results,
                require(
                    client.get(f"/api/v1/assessments/{assessment['id']}/evidence"), 200
                ),
                plugins,
            )
            if check_resources:
                verify_resource_removal(assessment["id"])
            expected_actions.extend(
                ("assessment.queued", "assessment.running", "assessment.completed")
            )
            case.update(
                assessment_id=assessment["id"],
                assessment_url=f"{base_url.rstrip('/')}/dashboard/assessments/{assessment['id']}",
                results=results,
                evidence=evidence,
                passed=True,
            )
        audit = require(
            client.get(f"/api/v1/projects/{project['id']}/audit-events"), 200
        )
        if [event["action"] for event in audit] != expected_actions:
            raise RuntimeError(
                "Demo project's audit trail does not match the completed workflow"
            )
        report.update(
            audit=audit,
            passed=None if register_only else True,
            resources_checked=check_resources and not register_only,
        )
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout-seconds", type=positive_timeout, default=120)
    parser.add_argument("--project-name", default="Northstar Workspace | Plugin demo")
    parser.add_argument(
        "--case",
        action="append",
        choices=[scenario.path for scenario in (*SCENARIOS, *COOKIE_SCENARIOS)],
        help="Assess only the selected paths; repeat for multiple cases",
    )
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="Register the project and target for manual GUI testing",
    )
    parser.add_argument(
        "--skip-resource-check",
        action="store_true",
        help="For a remote Docker daemon; still require API cleanup verification",
    )
    parser.add_argument(
        "--output", type=Path, help="Save the detailed JSON verification report"
    )
    args = parser.parse_args()
    from app.core.config import settings

    try:
        selected = tuple(
            scenario
            for scenario in (*SCENARIOS, *COOKIE_SCENARIOS)
            if args.case is None or scenario.path in args.case
        )
        report = verify(
            args.base_url or settings.api_base_url,
            scenarios=selected,
            timeout_seconds=args.timeout_seconds,
            project_name=args.project_name,
            register_only=args.register_only,
            check_resources=not args.skip_resource_check,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        print(
            json.dumps(
                {
                    "project_url": report["project_url"],
                    "cases": len(report["cases"]),
                    "passed": report["passed"],
                    "resources_checked": report["resources_checked"],
                    "report": str(args.output) if args.output else None,
                },
                indent=2,
            )
        )
    except Exception as error:
        print(f"Demo verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
