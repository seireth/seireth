"""Shared route execution, durable publication, and strict release decisions."""

from pydantic import ValidationError
from sqlalchemy import select

from ..persistence import models
from ..plugins.base import AnalysisContext
from ..plugins.registry import registry
from .execution import Cancelled, Interrupted
from .lifecycle import latest_attempt
from .orchestrator import Outcome, PluginExecutionError, analyze_response
from .policy import PolicyError, public_response_url


def serialized_results(results):
    from ..api.schemas import EvidenceOut

    serialized = []
    for item in results:
        for finding in item.findings:
            try:
                EvidenceOut.model_validate(
                    {
                        "id": "validation",
                        "finding_id": "validation",
                        "kind": "http-response",
                        "data": finding.evidence,
                    }
                )
            except ValidationError:
                raise PluginExecutionError(item.plugin_id, invalid=True) from None
        serialized.append(
            {
                "id": item.plugin_id,
                "findings": [
                    finding.model_dump(mode="json") for finding in item.findings
                ],
                "checks": [check.model_dump() for check in item.checks],
            }
        )
    return serialized


def execute_plan(session, snapshot, context, persist_route):
    outcome = Outcome()
    attempted = set()
    try:
        context.check()
        session.prepare()
        for route in snapshot["routes"]:
            context.check()
            data = {
                "key": route["key"],
                "url": route["url"],
                "started_at": models.now().isoformat(),
            }
            try:
                response = session.fetch(route)
                observation = response["observation"]
                plugins = registry.select(route["plugins"])
                results = analyze_response(
                    observation,
                    plugins,
                    context,
                    AnalysisContext.model_validate(route["analysis"]),
                )
                data.update(
                    status="completed",
                    response={
                        "status_code": observation.status_code,
                        "media_type": observation.media_type,
                        "url": str(observation.url),
                        "redirects": response["redirects"],
                    },
                    plugins=serialized_results(results),
                )
            except Cancelled, Interrupted:
                raise
            except PluginExecutionError as error:
                data.update(
                    status="failed",
                    error=str(error),
                    error_kind="plugin_error",
                    failed_plugin=error.plugin_id,
                )
            except TimeoutError:
                context.check()
                data.update(
                    status="failed",
                    error="route request timed out",
                    error_kind="timeout",
                )
            except PolicyError as error:
                data.update(
                    status="failed", error=str(error), error_kind="execution_error"
                )
            except Exception:
                context.check()
                data.update(
                    status="failed",
                    error="route execution failed",
                    error_kind="execution_error",
                )
            if data["status"] == "failed":
                outcome.status = "failed"
                outcome.error = data["error"]
                outcome.error_kind = data["error_kind"]
                outcome.failed_plugin = data.get("failed_plugin")
            data["finished_at"] = models.now().isoformat()
            persist_route(data)
            attempted.add(route["key"])
    except Cancelled:
        outcome = Outcome("cancelled", "assessment cancelled")
    except Interrupted:
        outcome = Outcome("recovering", "execution interrupted")
    except TimeoutError:
        outcome = Outcome(
            "failed", "assessment execution timed out", error_kind="timeout"
        )
    except PolicyError as error:
        outcome = Outcome("failed", str(error), error_kind="execution_error")
    except Exception:
        outcome = Outcome(
            "failed", "assessment execution failed", error_kind="execution_error"
        )
    finally:
        outcome.execution_status = outcome.status
        # Interrupted writers cannot advance records. A new owner fills missing
        # routes from the frozen plan while recovering the attempt.
        if outcome.status != "recovering":
            for route in snapshot["routes"]:
                if route["key"] not in attempted:
                    try:
                        persist_route(
                            {
                                "key": route["key"],
                                "url": route["url"],
                                "status": "unattempted",
                                "error": outcome.error
                                or "execution did not reach this route",
                            }
                        )
                    except Interrupted:
                        break
        try:
            cleanup = session.cleanup()
            outcome.cleanup_verified, outcome.cleanup_reason = (
                cleanup.verified,
                cleanup.reason,
            )
        except Exception:
            outcome.cleanup_reason = "cleanup could not be completed"
        if not outcome.cleanup_verified:
            outcome.status = "failed"
            outcome.error = outcome.error or "cleanup could not be verified"
    return outcome


def route_rows(db, attempt):
    return list(
        db.scalars(
            select(models.RouteResult)
            .where(models.RouteResult.attempt_id == attempt.id)
            .order_by(models.RouteResult.created_at, models.RouteResult.id)
        )
    )


def public_findings(db, assessment):
    if (
        assessment.status not in {"completed", "failed", "cancelled"}
        or assessment.cleanup_pending
    ):
        return []
    attempt = latest_attempt(db, assessment.id)
    if not attempt or not attempt.cleanup_verified:
        return []
    return list(
        db.scalars(
            select(models.Finding)
            .join(models.RouteResult)
            .where(
                models.Finding.assessment_id == assessment.id,
                models.RouteResult.attempt_id == attempt.id,
                models.RouteResult.status == "completed",
            )
            .order_by(models.Finding.id)
        )
    )


def summarize(db, assessment, attempt=None):
    snapshot = assessment.plan_snapshot
    rows = {row.route_key: row for row in route_rows(db, attempt)} if attempt else {}
    cleaned = (
        attempt.cleanup_verified if attempt else assessment.result["cleanup_verified"]
    )
    summaries, reasons = [], []
    total = 0
    for route in snapshot["routes"]:
        row = rows.get(route["key"])
        data = (
            row.data
            if row
            else {
                "status": "unattempted",
                "error": assessment.result.get(
                    "error", "execution interrupted before this route finished"
                ),
            }
        )
        plugins = data.get("plugins", [])
        checks = {
            f"{item['id']}:{check['rule_id']}": check
            for item in plugins
            for check in item["checks"]
        }
        missing = [
            rule
            for rule in route["required_checks"]
            if rule not in checks
            or checks[rule]["status"] in {"skipped", "inconclusive"}
        ]
        if not route["required_checks"] and not route["required_checks_explicit"]:
            missing.append("plan:required-checks")
        failed = [
            rule
            for rule in route["required_checks"]
            if rule in checks and checks[rule]["status"] == "failed"
        ]
        response = data.get("response")
        expected = bool(
            response
            and response["status_code"] in route["expected"]["statuses"]
            and public_response_url(response["url"]) == route["expected"]["final_url"]
            and (
                not route["expected"]["media_types"]
                or response["media_type"] in route["expected"]["media_types"]
            )
        )
        count = sum(len(item["findings"]) for item in plugins)
        total += count
        if data["status"] != "completed" or not expected or missing or failed or count:
            reasons.append(f"route {route['key']} did not satisfy the release policy")
        summaries.append(
            {
                "id": row.id if row else None,
                **{key: value for key, value in data.items() if key != "plugins"},
                "key": route["key"],
                "url": route["url"],
                "plugins": [
                    {key: value for key, value in item.items() if key != "findings"}
                    | {"finding_count": len(item["findings"])}
                    for item in plugins
                ],
                "finding_count": count,
                "coverage": {
                    "complete": data["status"] == "completed"
                    and expected
                    and not missing,
                    "expected_response": expected,
                    "missing_checks": missing,
                    "failed_checks": failed,
                },
            }
        )
    if assessment.result["execution_outcome"] != "completed":
        reasons.append("execution did not complete")
    elif assessment.status != "completed":
        reasons.append("assessment was unsuccessful before cleanup reconciliation")
    if not cleaned:
        reasons.append("cleanup is not verified")
    assessment.result = {
        **assessment.result,
        "routes": summaries,
        "finding_count": total if cleaned else 0,
        "coverage": {
            "complete": all(route["coverage"]["complete"] for route in summaries)
        },
        "verdict": {
            "policy": snapshot["policy"],
            "status": "blocked" if reasons else "pass",
            "reasons": reasons,
        },
        "partial": assessment.status != "completed"
        and any(route["status"] == "completed" for route in summaries),
    }


def finding_identity(route, plugin, evidence):
    rule = evidence.get("rule_id", evidence.get("rule"))
    entity = evidence.get("cookie_name", evidence.get("header"))
    if not rule or not entity:
        return None
    return route, plugin, rule, entity


def refresh_result(db, assessment, attempt=None):
    """Rebuild the same persisted projection after execution or reconciliation."""
    summarize(db, assessment, attempt)
    db.flush()
    assessment.result = {**assessment.result, "comparison": compare(db, assessment)}


def comparison_signature(snapshot):
    return {
        "kind": snapshot["target"]["kind"],
        "target_url": snapshot["target"]["url"],
        "plugins": snapshot["plugins"],
        "routes": [
            {
                key: route[key]
                for key in (
                    "key",
                    "url",
                    "plugins",
                    "request",
                    "expected",
                    "required_checks",
                    "analysis",
                )
            }
            for route in snapshot["routes"]
        ],
    }


def compare(db, assessment):
    identifier = assessment.plan_snapshot["baseline"]
    if not identifier:
        return {"status": "not_requested"}
    baseline = db.get(models.Assessment, identifier)
    if not baseline or baseline.project_id != assessment.project_id:
        return {"status": "unavailable", "reason": "compatible baseline is unavailable"}
    if comparison_signature(baseline.plan_snapshot) != comparison_signature(
        assessment.plan_snapshot
    ):
        return {
            "status": "unavailable",
            "reason": "baseline configuration or plugin versions differ",
        }
    if any(
        item.status != "completed"
        or item.cleanup_pending
        or not item.result["coverage"]["complete"]
        for item in (baseline, assessment)
    ):
        return {
            "status": "unavailable",
            "reason": "complete execution and coverage are required",
        }

    def identities(item):
        findings = public_findings(db, item)
        if not findings:
            return set()
        keys = set()
        covered = set()
        for finding_id, route, plugin, evidence in db.execute(
            select(
                models.Finding.id,
                models.RouteResult.route_key,
                models.Finding.plugin,
                models.Evidence.data,
            )
            .select_from(models.Finding)
            .join(models.RouteResult)
            .join(models.Evidence)
            .where(models.Finding.id.in_([finding.id for finding in findings]))
        ):
            identity = finding_identity(route, plugin, evidence)
            if identity is None:
                return None
            covered.add(finding_id)
            keys.add(identity)
        if len(covered) != len(findings):
            return None
        return keys

    before, after = identities(baseline), identities(assessment)
    if before is None or after is None:
        return {
            "status": "unavailable",
            "reason": "stable finding identities are unavailable",
        }
    return {
        "status": "available",
        "algorithm": 1,
        "baseline": baseline.id,
        "new": [list(key) for key in sorted(after - before)],
        "resolved": [list(key) for key in sorted(before - after)],
        "unchanged": [list(key) for key in sorted(before & after)],
    }
