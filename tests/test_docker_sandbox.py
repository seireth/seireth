import json

from app.sandbox import DockerSandbox


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_docker_sandbox_builds_restricted_private_network_commands(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["run", "-d"]:
            return Completed(stdout="target-id")
        if argv[1:3] == ["run", "--rm"]:
            return Completed(stdout=json.dumps({"X-Test": "ok"}))
        if argv[1:3] == ["network", "inspect"]:
            return Completed(returncode=1)
        return Completed()

    monkeypatch.setattr("app.sandbox.subprocess.run", fake_run)
    sandbox = DockerSandbox(
        "demo:local", target_host="demo-target", target_label="demo-target"
    )

    assert sandbox.execute("http://demo-target:8080").headers == {"X-Test": "ok"}
    assert sandbox.cleanup()
    assert any("--internal" in command for command in calls)
    target = next(command for command in calls if command[1:3] == ["run", "-d"])
    runner = next(command for command in calls if command[1:3] == ["run", "--rm"])
    assert "--name" in target
    assert any(value.startswith("seireth-target-demo-target-") for value in target)
    assert any(value.startswith("seireth-assessment-runner-") for value in runner)
    assert "--label" not in target
    assert "--label" not in runner
    assert "--read-only" in target
    assert "--cap-drop=ALL" in target
    assert "--security-opt=no-new-privileges" in target
    assert "--network=host" not in target
    removed = [command for command in calls if command[1:3] == ["rm", "-f"]]
    assert any(sandbox.runner_name in command for command in removed)
    assert any(sandbox.target_name in command for command in removed)


def test_docker_sandbox_cleans_up_when_target_start_fails(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["run", "-d"]:
            return Completed(returncode=1, stderr="bad image")
        if argv[1:3] == ["network", "inspect"]:
            return Completed(returncode=1)
        return Completed()

    monkeypatch.setattr("app.sandbox.subprocess.run", fake_run)
    sandbox = DockerSandbox("demo:local", target_host="demo-target")

    try:
        sandbox.execute("http://demo-target:8080")
    except RuntimeError:
        pass
    else:
        raise AssertionError("target startup should fail")
    assert sandbox.cleanup()
    assert any(command[1:3] == ["rm", "-f"] for command in calls)
    assert any(command[1:3] == ["network", "rm"] for command in calls)


def test_docker_sandbox_rejects_network_names_that_would_exceed_docker_limit():
    import pytest

    with pytest.raises(ValueError):
        DockerSandbox("demo:local", network_prefix="a" * 51)
