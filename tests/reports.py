"""Complete current reports for transport and CLI contract tests."""

from types import SimpleNamespace

from app.api.schemas import AssessmentReportOut
from app.assessments.lifecycle import terminal_result
from app.persistence import models
from tests.sessions import execution_metadata, frozen_plan


def report_fixture(*, status="completed", verdict="pass", pending=False):
    target = SimpleNamespace(
        id="target",
        project_id="project",
        name="Fixture",
        kind="website",
        image=None,
        url="https://fixture.test/",
        launch_profile=None,
        network_profile=None,
        trust_profile=None,
    )
    plan = frozen_plan(target=target)
    route = plan["routes"][0]
    complete = status == "completed" and verdict == "pass"
    metadata = execution_metadata(plan)
    attempt = SimpleNamespace(
        backend="http",
        number=1,
        finished_at=models.now(),
        execution_metadata=metadata,
    )
    result = terminal_result(
        attempt=attempt, execution_outcome=status, cleanup_verified=not pending
    )
    result.update(
        routes=[
            {
                "key": route["key"],
                "url": route["url"],
                "status": "completed" if status == "completed" else "unattempted",
                **(
                    {
                        "response": {
                            "status_code": 200,
                            "media_type": "text/html",
                            "url": route["url"],
                            "redirects": [],
                        }
                    }
                    if status == "completed"
                    else {}
                ),
                "plugins": [
                    {
                        "id": "http-security-headers",
                        "finding_count": 0,
                        "checks": [
                            {
                                "rule_id": rule.split(":")[1],
                                "status": "passed" if complete else "inconclusive",
                                "reason": "Controlled response evaluated.",
                            }
                            for rule in route["required_checks"]
                        ],
                    }
                ]
                if status == "completed"
                else [],
                "finding_count": 0,
                "coverage": {
                    "complete": complete,
                    "expected_response": status == "completed",
                    "missing_checks": [] if complete else route["required_checks"],
                    "failed_checks": [],
                },
            }
        ],
        coverage={"complete": complete},
        verdict={
            "policy": "strict-v1",
            "status": verdict,
            "reasons": []
            if verdict == "pass"
            else ["Required coverage is incomplete."],
        },
    )
    report = {
        "schema_version": 1,
        "generated_at": result["completed_at"],
        "project": {
            "id": "project",
            "name": "Test",
            "created_at": result["completed_at"],
        },
        "target": plan["target"],
        "assessment": {
            "id": "assessment",
            "project_id": "project",
            "target_id": "target",
            "url": route["url"],
            "plugins": ["http-security-headers"],
            "created_at": result["completed_at"],
            "status": status,
            "cleanup_pending": pending,
            "plan_snapshot": plan,
            "result": result,
        },
        "findings": [],
        "evidence": [],
    }
    return AssessmentReportOut.model_validate(report).model_dump(
        mode="json", exclude_unset=True
    )
