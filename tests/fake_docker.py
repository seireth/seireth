"""Deterministic daemon state for delayed-creation and recovery tests."""

import hashlib
import json
import subprocess


class FakeDocker:
    def __init__(self):
        self.live = {}
        self.calls = []
        self.create_hook = None
        self.available = True
        self.headers = {}
        self.kept = set()
        self.remove_error = False
        self.runner_status = 0
        self.runner_output = None
        self.unsupported_calls = []

    def add(self, sandbox, kind, labels=None):
        name = sandbox.resources[kind]
        identity = hashlib.sha256(name.encode()).hexdigest()
        labels = dict(sandbox.labels if labels is None else labels)
        self.live[name] = {
            "kind": kind,
            "Id": identity,
            "Labels": labels,
            "Config": {"Labels": labels},
        }
        return identity

    def run(self, sandbox, args, timeout, *, interruptible=True):
        sandbox._guard(advancing=interruptible)
        self.calls.append(args)
        if not self.available:
            return subprocess.CompletedProcess(args, 1, "", "daemon unavailable")
        if args[:2] == ["network", "create"] or args[0] == "create":
            name = args[-1] if args[0] == "network" else args[args.index("--name") + 1]
            kind = next(
                kind for kind, value in sandbox.resources.items() if value == name
            )
            if self.create_hook:
                self.create_hook(sandbox, kind)
            labels = dict(
                args[index + 1].split("=", 1)
                for index, arg in enumerate(args)
                if arg == "--label"
            )
            output = self.add(sandbox, kind, labels)
        elif args[:2] == ["network", "ls"] or args[0] == "ps":
            network = args[0] == "network"
            output = "\n".join(
                name
                for name, record in self.live.items()
                if (record["kind"] == "network") is network
            )
        elif args[:2] in (["network", "inspect"], ["container", "inspect"]):
            record = self.live.get(args[-1])
            if not record or (record["kind"] == "network") is not (
                args[0] == "network"
            ):
                return subprocess.CompletedProcess(args, 1, "", "resource not found")
            output = json.dumps([record])
        elif args[0] == "rm" or args[:2] == ["network", "rm"]:
            if self.remove_error:
                return subprocess.CompletedProcess(args, 1, "", "removal failed")
            for name, resource in list(self.live.items()):
                if resource["Id"] == args[-1] and name not in self.kept:
                    if (resource["kind"] == "network") is not (args[0] == "network"):
                        return subprocess.CompletedProcess(
                            args, 1, "", "wrong resource type"
                        )
                    del self.live[name]
            output = args[-1]
        elif args[0] == "start":
            record = next(
                (record for record in self.live.values() if record["Id"] == args[-1]),
                None,
            )
            if not record or record["kind"] == "network":
                return subprocess.CompletedProcess(args, 1, "", "container not found")
            if "--attach" in args:
                assert record["kind"] == "runner"
                output = (
                    json.dumps(self.headers)
                    if self.runner_output is None
                    else self.runner_output
                )
                return subprocess.CompletedProcess(
                    args,
                    self.runner_status,
                    output,
                    "runner error" if self.runner_status else "",
                )
            output = args[-1]
        else:
            self.unsupported_calls.append(args)
            raise RuntimeError(f"unsupported fake Docker command: {args!r}")
        return subprocess.CompletedProcess(args, 0, output, "")

    def install(self, monkeypatch):
        from app.sandbox import DockerSandbox

        monkeypatch.setattr(
            DockerSandbox,
            "_run",
            lambda sandbox, *args, **kwargs: self.run(sandbox, *args, **kwargs),
        )
