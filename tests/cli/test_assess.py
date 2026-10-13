"""Release CLI saves reports before returning every terminal exit code."""

import json

import httpx
import pytest

from app.cli.assess import assess
from tests.sessions import frozen_plan


@pytest.mark.parametrize(
    "status,verdict,pending,exit_code",
    [
        ("completed", "pass", False, 0),
        ("completed", "blocked", False, 2),
        ("failed", "blocked", False, 1),
        ("cancelled", "blocked", False, 1),
        ("completed", "blocked", True, 1),
    ],
)
def test_cli_persists_terminal_report_before_returning_exit_code(
    monkeypatch, tmp_path, mock_images, status, verdict, pending, exit_code
):
    plan = tmp_path / "routes.json"
    plan.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "key": "root",
                        "url": "https://fixture.test/",
                        "plugins": ["http-security-headers"],
                    }
                ]
            }
        )
    )
    snapshot = frozen_plan()
    report = {
        "schema_version": 1,
        "generated_at": "2026-10-12T10:00:00Z",
        "project": {
            "id": "project",
            "name": "Test",
            "created_at": "2026-10-12T10:00:00Z",
        },
        "target": snapshot["target"],
        "assessment": {
            "id": "assessment",
            "project_id": "project",
            "target_id": "target",
            "url": snapshot["routes"][0]["url"],
            "plugins": ["http-security-headers"],
            "created_at": "2026-10-12T10:00:00Z",
            "status": status,
            "cleanup_pending": pending,
            "plan_snapshot": snapshot,
            "result": {
                "execution_outcome": status,
                "cleanup_verified": not pending,
                "finding_count": 0,
                "routes": [],
                "coverage": {"complete": verdict == "pass"},
                "partial": False,
                "comparison": {"status": "not_requested"},
                "verdict": {"status": verdict, "policy": "strict-v1", "reasons": []},
            },
        },
        "findings": [],
        "evidence": [],
    }

    def respond(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["baseline"] == "baseline"
            return httpx.Response(
                202, json={"id": "assessment", "plan_snapshot": snapshot}
            )
        if request.url.path.endswith("/results"):
            return httpx.Response(
                200,
                json={
                    "status": status,
                    "cleanup_pending": pending,
                    "result": {"verdict": {"status": verdict}},
                },
            )
        return httpx.Response(200, json=report)

    factory = httpx.Client
    monkeypatch.setattr(
        "app.cli.assess.httpx.Client",
        lambda **kwargs: factory(transport=httpx.MockTransport(respond), **kwargs),
    )
    output = tmp_path / "report.json"
    assert (
        assess(
            "http://api.test",
            project_id="project",
            target_id="target",
            plan=plan,
            baseline="baseline",
            output=output,
        )
        == exit_code
    )
    assert json.loads(output.read_text()) == report
