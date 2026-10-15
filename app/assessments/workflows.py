"""Shared route execution, durable publication, and strict release decisions."""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select

from ..persistence import models
from ..plugins.base import AnalysisContext, PluginResponse, PluginResult
from ..plugins.evidence import evidence_adapter
from ..plugins.registry import registry
from .execution import Cancelled, Interrupted
from .lifecycle import latest_attempt
from .plans import read_snapshot
from .policy import PolicyError, public_response_url
from .results import AssessmentResult


@dataclass
class Outcome:
    status: str = "completed"
    error: str | None = None
    cleanup_verified: bool = False
    cleanup_reason: str | None = None
    error_kind: str | None = None
    failed_plugin: str | None = None
    execution_status: str | None = None


class PluginExecutionError(RuntimeError):
    """A safe plugin failure description, separate from security findings."""

    def __init__(self, plugin_id, *, invalid=False):
        self.plugin_id = plugin_id
        super().__init__(
            f"plugin {plugin_id} returned an invalid response"
            if invalid
            else f"plugin {plugin_id} execution failed"
        )


def analyze_response(observation, plugins, context, analysis):
    results = []
    for plugin in plugins:
        try:
            value = plugin.analyze(observation.model_copy(deep=True), analysis)
            response = PluginResponse.model_validate(value, strict=True)
        except ValidationError as exc:
            raise PluginExecutionError(plugin.manifest.id, invalid=True) from exc
        except Exception as exc:
            raise PluginExecutionError(plugin.manifest.id) from exc
        results.append(
            PluginResult(plugin.manifest.id, response.findings, response.checks)
        )
        context.check()
    return results


def validate_evidence(results):
    for item in results:
        for finding in item.findings:
            try:
                evidence_adapter.validate_python(finding.evidence, strict=True)
            except ValidationError:
                raise PluginExecutionError(item.plugin_id, invalid=True) from None


def execute_plan(session, snapshot, context, persist_route):
    outcome = Outcome()
    attempted = set()
    try:
        context.check()
        session.prepare()
        for route in snapshot["routes"]:
            context.check()
            results = ()
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
                validate_evidence(results)
                data.update(
                    status="completed",
                    response={
                        "status_code": observation.status_code,
                        "media_type": observation.media_type,
                        "url": str(observation.url),
                        "redirects": response["redirects"],
                    },
                    plugins=[
                        {
                            "id": item.plugin_id,
                            "checks": [check.model_dump() for check in item.checks],
                        }
                        for item in results
                    ],
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
                results = ()
                outcome.status = "failed"
                outcome.error = data["error"]
                outcome.error_kind = data["error_kind"]
                outcome.failed_plugin = data.get("failed_plugin")
            data["finished_at"] = models.now().isoformat()
            persist_route(data, results)
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
        try:
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
                                },
                                (),
                            )
                        except Interrupted:
                            break
                        except Exception:
                            # Recording placeholders must not discard socket
                            # closure proof when route persistence is unavailable.
                            outcome.status = outcome.execution_status = "failed"
                            outcome.error = "route results could not be recorded"
                            outcome.error_kind = "execution_error"
                            outcome.failed_plugin = None
                            break
        finally:
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


def publication_scope(db, assessment):
    if (
        assessment.status not in {"completed", "failed", "cancelled"}
        or assessment.cleanup_pending
    ):
        return None
    attempt = latest_attempt(db, assessment.id)
    if not attempt or not attempt.cleanup_verified:
        return None
    return (
        models.Finding.assessment_id == assessment.id,
        models.RouteResult.attempt_id == attempt.id,
        models.RouteResult.status == "completed",
    )


def published_findings(db, assessment):
    scope = publication_scope(db, assessment)
    if scope is None:
        return []
    return list(
        db.scalars(
            select(models.Finding)
            .join(models.RouteResult)
            .where(*scope)
            .order_by(models.Finding.id)
        )
    )


def published_evidence(db, assessment):
    scope = publication_scope(db, assessment)
    if scope is None:
        return []
    return list(
        db.scalars(
            select(models.Evidence)
            .join(models.Finding)
            .join(models.RouteResult)
            .where(*scope)
            .order_by(models.Evidence.id)
        )
    )


def published_records(db, assessment):
    """Select findings and evidence from one eligible attempt together."""
    scope = publication_scope(db, assessment)
    if scope is None:
        return [], []
    rows = db.execute(
        select(models.Finding, models.Evidence)
        .join(models.RouteResult)
        .outerjoin(models.Evidence)
        .where(*scope)
        .order_by(models.Finding.id, models.Evidence.id)
    )
    findings, evidence = {}, []
    for finding, entry in rows:
        findings[finding.id] = finding
        if entry is not None:
            evidence.append(entry)
    return list(findings.values()), sorted(evidence, key=lambda entry: entry.id)


def refresh_result(db, assessment, attempt=None):
    """Rebuild the persisted projection after execution or reconciliation."""
    snapshot = read_snapshot(assessment.plan_snapshot).model_dump(mode="json")
    rows = {row.route_key: row for row in route_rows(db, attempt)} if attempt else {}
    counts = (
        dict(
            ((route_id, plugin), count)
            for route_id, plugin, count in db.execute(
                select(
                    models.Finding.route_result_id, models.Finding.plugin, func.count()
                )
                .join(models.RouteResult)
                .where(
                    models.RouteResult.attempt_id == attempt.id,
                    models.RouteResult.status == "completed",
                )
                .group_by(models.Finding.route_result_id, models.Finding.plugin)
            )
        )
        if attempt
        else {}
    )
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
        plugin_counts = (
            {item["id"]: counts.get((row.id, item["id"]), 0) for item in plugins}
            if row
            else {}
        )
        count = sum(plugin_counts.values())
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
                    item
                    | {"finding_count": plugin_counts[item["id"]] if cleaned else 0}
                    for item in plugins
                ],
                "finding_count": count if cleaned else 0,
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
    db.flush()
    assessment.result = {
        **assessment.result,
        "comparison": compare(db, assessment, snapshot),
    }
    assessment.result = AssessmentResult.model_validate(assessment.result).model_dump(
        mode="json", exclude_unset=True
    )


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


def compare(db, assessment, snapshot):
    identifier = snapshot["baseline"]
    if not identifier:
        return {"status": "not_requested"}
    baseline = db.get(models.Assessment, identifier)
    if not baseline or baseline.project_id != assessment.project_id:
        return {"status": "unavailable", "reason": "compatible baseline is unavailable"}
    try:
        compatible = comparison_signature(
            read_snapshot(baseline.plan_snapshot).model_dump(mode="json")
        ) == comparison_signature(snapshot)
    except ValidationError:
        return {"status": "unavailable", "reason": "baseline configuration is invalid"}
    if not compatible:
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
        scope = publication_scope(db, item)
        if scope is None:
            return None
        keys = set()
        for route, plugin, evidence in db.execute(
            select(
                models.RouteResult.route_key,
                models.Finding.plugin,
                models.Evidence.data,
            )
            .select_from(models.Finding)
            .join(models.RouteResult)
            .outerjoin(models.Evidence)
            .where(*scope)
        ):
            if evidence is None:
                return None
            try:
                evidence = evidence_adapter.validate_python(
                    evidence, strict=True
                ).model_dump(mode="json")
            except ValidationError:
                return None
            keys.add(
                (
                    route,
                    plugin,
                    evidence["rule_id"],
                    evidence.get("cookie_name", evidence["header"]),
                )
            )
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
