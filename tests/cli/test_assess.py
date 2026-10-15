"""Release CLI saves reports before returning every terminal exit code."""

import json

import httpx
import pytest

from app.cli.assess import assess
from tests.reports import report_fixture


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
    monkeypatch, tmp_path, status, verdict, pending, exit_code
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
    report = report_fixture(status=status, verdict=verdict, pending=pending)
    snapshot = report["assessment"]["plan_snapshot"]

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
        assert request.url.path.endswith("/report")
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
