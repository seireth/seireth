"""Submit a persisted route plan and enforce its stored release verdict."""

import json
import sys
from pathlib import Path

import httpx

from .verify import require, wait_for_results


def assess(base_url, *, project_id, target_id, plan, baseline=None, output=None):
    from ..api.schemas import AssessmentReportOut

    try:
        payload = json.loads(Path(plan).read_text(encoding="utf-8"))
        routes = payload["routes"] if isinstance(payload, dict) else payload
        with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
            submission = require(
                client.post(
                    "/api/v1/assessments",
                    json={
                        "project_id": project_id,
                        "target_id": target_id,
                        "routes": routes,
                        "baseline": baseline,
                    },
                ),
                202,
            )
            snapshot = submission["plan_snapshot"]
            wait_for_results(
                client,
                submission["id"],
                snapshot["timeout_seconds"] + snapshot["cleanup_seconds"] + 30,
            )
            report = require(
                client.get(f"/api/v1/assessments/{submission['id']}/report"), 200
            )
            AssessmentReportOut.model_validate(report)
            serialized = json.dumps(report, indent=2)
            if output:
                Path(output).write_text(serialized + "\n", encoding="utf-8")
            else:
                print(serialized)
            assessment = report["assessment"]
            if assessment["status"] != "completed" or assessment["cleanup_pending"]:
                return 1
            return 0 if assessment["result"]["verdict"]["status"] == "pass" else 2
    except Exception:
        print(
            "assessment command failed; inspect the API assessment state",
            file=sys.stderr,
        )
        return 1
