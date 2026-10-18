"""Route execution isolates plugins and publishes routes atomically."""

import pytest

from app.assessments import execution, workflows
from app.plugins.base import PluginFinding, PluginResponse
from app.plugins.registry import PluginRegistry
from tests.sessions import FakeSession, frozen_plan


@pytest.fixture
def run_plan(monkeypatch, mock_images, execution_context):
    def run(plugins, *, routes=1, cleanup=None):
        monkeypatch.setattr(workflows, "registry", PluginRegistry(tuple(plugins)))
        snapshot = frozen_plan()
        route = snapshot["routes"][0]
        route["plugins"] = [plugin.manifest.id for plugin in plugins]
        snapshot["routes"] = [{**route, "key": str(index)} for index in range(routes)]
        session = FakeSession(
            snapshot, context=execution_context, persist_journal=lambda *a, **kw: None
        )
        if cleanup is not None:
            session.cleanup = cleanup
        saved = []
        outcome = workflows.execute_plan(
            session,
            snapshot,
            execution_context,
            lambda data, results: saved.append(data),
        )
        return outcome, saved

    return run


def test_plugins_receive_independent_observations(run_plan, make_plugin):
    calls = []

    def first(observation, context):
        observation.headers["content-type"].append("application/json")
        calls.append("first")
        return PluginResponse(findings=(), checks=())

    def second(observation, context):
        assert observation.headers == {"content-type": ["text/html"]}
        calls.append("second")
        return PluginResponse(findings=(), checks=())

    outcome, saved = run_plan(
        [make_plugin("first", first), make_plugin("second", second)]
    )
    assert outcome.status == "completed" and outcome.cleanup_verified
    assert calls == ["first", "second"]
    assert len(saved) == 1 and saved[0]["status"] == "completed"
    assert [plugin["id"] for plugin in saved[0]["plugins"]] == calls


@pytest.mark.parametrize(
    "mode",
    [
        "crash",
        "invalid",
        "signature",
        "missing-checks",
        "blank-description",
        "blank-remediation",
    ],
)
def test_invalid_plugin_response_fails_routes_and_cleans(
    run_plan, make_plugin, mode, caplog
):
    def broken(observation, context):
        if mode == "crash":
            raise RuntimeError("secret-runtime-value")
        if mode == "invalid":
            return object()
        if mode == "missing-checks":
            return PluginResponse.model_construct(findings=())
        values = dict(
            title="Example",
            severity="low",
            description="Example",
            remediation="Fix",
            evidence={},
        )
        values[mode.removeprefix("blank-")] = " \t\n"
        return PluginResponse.model_construct(
            findings=(PluginFinding.model_construct(**values),), checks=()
        )

    analyzer = (lambda: None) if mode == "signature" else broken
    outcome, saved = run_plan([make_plugin("broken", analyzer)], routes=2)
    assert outcome.status == "failed" and outcome.cleanup_verified
    assert outcome.error_kind == "plugin_error"
    assert all(row["status"] == "failed" and "plugins" not in row for row in saved)
    assert "secret-runtime-value" not in caplog.text


def test_analyzer_overrun_discards_route_and_cleans(
    run_plan, make_plugin, execution_context, monkeypatch
):
    monkeypatch.setattr(execution, "monotonic", lambda: 0)
    execution_context.deadline = 1

    def delayed(observation, context):
        monkeypatch.setattr(execution, "monotonic", lambda: 1)
        return PluginResponse(findings=(), checks=())

    outcome, saved = run_plan([make_plugin("delayed", delayed)], routes=2)
    assert outcome.status == outcome.execution_status == "failed"
    assert outcome.error_kind == "timeout" and outcome.failed_plugin is None
    assert outcome.cleanup_verified
    assert len(saved) == 2 and all(row["status"] == "unattempted" for row in saved)


def test_cleanup_exception_blocks_completed_route(run_plan, make_plugin):
    def cleanup():
        raise OSError("secret-cleanup-value")

    outcome, saved = run_plan(
        [
            make_plugin(
                "valid",
                lambda observation, context: PluginResponse(findings=(), checks=()),
            )
        ],
        cleanup=cleanup,
    )
    assert saved[0]["status"] == "completed"
    assert outcome.status == "failed" and not outcome.cleanup_verified
    assert outcome.cleanup_reason == "cleanup could not be completed"
