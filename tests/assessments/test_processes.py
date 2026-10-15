"""Process/container lifetime evidence remains conservative across PID reuse."""

from app.assessments import processes


def test_current_process_cannot_be_certified_exited():
    assert not processes.identity_exited(processes.capture_identity())


def test_unknown_or_other_host_process_is_not_cleanup_proof():
    assert not processes.identity_exited(None)
    assert not processes.identity_exited({"pid": 1, "host": "another-host"})
    assert not processes.process_exited(True)


def test_docker_restart_proves_old_lifetime_ended_even_when_pid_is_one(monkeypatch):
    identity = {
        "pid": 1,
        "host": "old-container",
        "container": {"id": "a" * 64, "daemon": "owned-daemon", "started": "before"},
    }

    def docker(*args):
        return (
            "owned-daemon"
            if args[0] == "info"
            else [{"Id": "a" * 64, "State": {"Running": True, "StartedAt": "after"}}]
        )

    monkeypatch.setattr(processes, "docker_json", docker)
    assert processes.identity_exited(identity)
    monkeypatch.setattr(processes, "docker_json", lambda *args: "different-daemon")
    assert not processes.identity_exited(identity)
