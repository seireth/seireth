"""Bundle commands, interrupted processes, and conservative cleanup."""

import json
import subprocess
import sys
from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.assessments.bundle import BundleSession, validate_journal
from app.assessments.execution import Cancelled
from app.assessments.workflows import execute_plan
from app.core.config import settings
from tests.sessions import attempt_record, frozen_plan
from tests.website import tls_certificate


@pytest.fixture
def sandbox(mock_images, execution_context):
    plan = frozen_plan()
    attempt = attempt_record(plan=plan, assessment_id="assessment", number=1)
    return BundleSession(
        plan, attempt, context=execution_context, persist_journal=lambda *a, **kw: None
    )


def test_owned_restricted_bundle_is_reused_and_cleaned(sandbox, fake_docker):
    saved = []
    outcome = execute_plan(
        sandbox,
        sandbox.snapshot,
        sandbox.context,
        lambda data, results: saved.append(data),
    )
    assert outcome.status == "completed" and outcome.cleanup_verified
    assert saved[0]["response"]["url"] == "http://demo-app:8080/"
    creates = [args for args in fake_docker.calls if args[0] == "create"]
    assert len(creates) == 2 and "--internal" in fake_docker.calls[0]
    for args in creates:
        for flag in (
            "--pull=never",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65532:65532",
            "--memory=256m",
            "--cpus=0.5",
            "--pids-limit=64",
        ):
            assert flag in args
        assert "seireth.assessment=assessment" in args
    assert not fake_docker.live
    assert all(
        entry["state"] == "removed" for entry in sandbox.journal["resources"].values()
    )


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_readiness_preserves_registered_host_query_and_certificate_trust(
    mock_images, execution_context, fake_docker, monkeypatch, tmp_path, scheme
):
    certificate, _ = tls_certificate(tmp_path, hostname="owned.test")
    target = SimpleNamespace(**frozen_plan()["target"])
    target.url = f"{scheme}://owned.test:8443/"
    target.launch_profile = target.trust_profile = "fixture"
    config = tmp_path / "operator.json"
    config.write_text(
        json.dumps(
            {
                "trusts": {"fixture": {"file": str(certificate)}},
                "launches": {
                    "fixture": {
                        "target": {
                            "readiness": {
                                "kind": scheme,
                                "port": 8443,
                                "path": "/health?full=1",
                            }
                        }
                    }
                },
            }
        )
    )
    monkeypatch.setattr(settings, "operator_config_file", str(config))
    plan = frozen_plan(target=target)
    attempt = attempt_record(plan=plan, assessment_id="assessment", number=1)
    sandbox = BundleSession(
        plan, attempt, context=execution_context, persist_journal=lambda *a, **kw: None
    )
    requests = []
    original = fake_docker.run

    def record(*args, **kwargs):
        if kwargs.get("input_data"):
            requests.append(json.loads(kwargs["input_data"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(fake_docker, "run", record)
    try:
        sandbox.prepare()
        assert requests[0]["url"] == target.url + "health?full=1"
        assert requests[0]["registered"] == target.url
        assert requests[0]["mapping"] == {"owned.test": "target"}
        assert requests[0]["ca"] == certificate.read_text()
        assert not requests[0]["headers"] and not requests[0]["follow_redirects"]
    finally:
        assert sandbox.cleanup().verified
    assert not fake_docker.live


@pytest.mark.parametrize(
    "output",
    ["not json", '{"observation":{"headers":{"set-cookie":["secret-cookie"]}}}'],
)
def test_invalid_runner_output_is_not_published_and_cleans(
    sandbox, fake_docker, output, caplog
):
    sandbox.prepare()
    fake_docker.runner_output = output
    with pytest.raises(Exception):
        sandbox.fetch(sandbox.snapshot["routes"][0])
    assert sandbox.cleanup().verified
    assert not fake_docker.live and "secret-cookie" not in caplog.text


@pytest.mark.parametrize("key", ["network", "target", "runner"])
def test_cleanup_verifies_every_owned_resource(sandbox, fake_docker, key):
    sandbox.prepare()
    fake_docker.kept.add(sandbox.resources[key])
    assert not sandbox.cleanup().verified
    fake_docker.kept.clear()
    assert sandbox.cleanup().verified


@pytest.mark.parametrize("label", ["seireth.assessment", "seireth.attempt"])
def test_cleanup_rejects_foreign_ownership(sandbox, fake_docker, label):
    sandbox.prepare()
    fake_docker.live[sandbox.resources["target"]]["Labels"][label] = "foreign"
    assert not sandbox.cleanup().verified
    assert sandbox.resources["target"] in fake_docker.live


def test_daemon_failure_is_not_verified_cleanup(sandbox, fake_docker):
    sandbox.prepare()
    fake_docker.available = False
    assert not sandbox.cleanup().verified


def test_uncertain_absence_remains_pending(sandbox, fake_docker):
    sandbox.journal["resources"]["network"]["state"] = "uncertain"
    assert not sandbox.cleanup().verified
    fake_docker.add(sandbox, "network")
    assert sandbox.cleanup().verified


def test_late_creation_records_identity_before_removal(sandbox, fake_docker):
    sandbox.journal["resources"]["network"]["state"] = "uncertain"
    fake_docker.add(sandbox, "network")
    recorded = []
    sandbox.persist_journal = lambda journal, **kw: recorded.append(deepcopy(journal))
    assert sandbox.cleanup().verified
    assert any(
        journal["resources"]["network"]["state"] == "created" for journal in recorded
    )


def test_known_identity_cannot_be_replaced(sandbox, fake_docker):
    sandbox.prepare()
    fake_docker.live[sandbox.resources["target"]]["Id"] = "b" * 64
    assert not sandbox.cleanup().verified
    assert sandbox.resources["target"] in fake_docker.live


@pytest.mark.parametrize("reason", ["cancel", "timeout", "cleanup-timeout"])
def test_real_subprocess_is_killed_and_reaped(sandbox, monkeypatch, reason):
    actual = subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = actual(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        )
        processes.append(process)
        if reason == "cancel":
            sandbox.context.cancel.set()
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    if reason == "cleanup-timeout":
        sandbox.context.cancel.set()
        sandbox._cleanup_deadline = monotonic() + 0.1
    started = monotonic()
    with pytest.raises(Cancelled if reason == "cancel" else TimeoutError):
        sandbox._run(
            ["info"],
            5 if reason == "cleanup-timeout" else 0.1,
            interruptible=reason != "cleanup-timeout",
        )
    assert len(processes) == 1 and processes[0].poll() is not None
    if reason == "cleanup-timeout":
        assert monotonic() - started < 4


def test_expired_cleanup_budget_does_not_start_a_command(sandbox, monkeypatch):
    sandbox._cleanup_deadline = monotonic() - 1
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)

    with pytest.raises(TimeoutError, match="cleanup budget exceeded"):
        sandbox._run(["info"], 5, interruptible=False)

    launch.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"owner": "x"},
        {"resources": []},
        {"unexpected": True},
    ],
)
def test_current_journal_rejects_invalid_fields(sandbox, changes):
    journal = {**deepcopy(sandbox.journal), **changes}
    with pytest.raises(ValueError, match="invalid operation journal"):
        validate_journal(journal)


@pytest.mark.parametrize(
    "change", [None, "missing", "unexpected", "kind", "name", "attempt"]
)
def test_journal_resources_must_match_the_attempt_bundle(sandbox, change):
    journal = deepcopy(sandbox.journal)
    attempt_id = sandbox.attempt_id
    resources = journal["resources"]
    if change == "missing":
        del resources["target"]
    elif change == "unexpected":
        resources["unexpected"] = deepcopy(resources["target"])
    elif change == "kind":
        resources["target"]["kind"] = "network"
    elif change == "name":
        resources["target"]["name"] = "seireth-other-target"
    elif change == "attempt":
        attempt_id = "other-attempt"
    # Every case is structurally valid; only bundle ownership distinguishes them.
    validate_journal(journal)
    if change is None:
        validate_journal(journal, snapshot=sandbox.snapshot, attempt_id=attempt_id)
    else:
        with pytest.raises(ValueError, match="invalid operation journal"):
            validate_journal(journal, snapshot=sandbox.snapshot, attempt_id=attempt_id)


@pytest.mark.parametrize("created_at", [None, "", " "])
def test_owned_volume_requires_creation_identity(sandbox, created_at):
    sandbox.journal["resources"]["volume-data"] = {
        "kind": "volume",
        "name": "seireth-volume-data",
        "state": "created",
        "id": "seireth-volume-data",
        "created_at": created_at,
    }
    with pytest.raises(ValueError, match="invalid operation journal"):
        validate_journal(sandbox.journal)
