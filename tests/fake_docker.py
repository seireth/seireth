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

    def add(self, sandbox, kind):
        name = sandbox.resources[kind]
        identity = hashlib.sha256(name.encode()).hexdigest()
        self.live[name] = {
            "Id": identity,
            "Labels": sandbox.labels,
            "Config": {"Labels": sandbox.labels},
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
            output = self.add(sandbox, kind)
        elif args[:2] == ["network", "ls"] or args[0] == "ps":
            output = "\n".join(self.live)
        elif "inspect" in args:
            output = json.dumps([self.live[args[-1]]])
        elif args[0] == "rm" or args[:2] == ["network", "rm"]:
            if self.remove_error:
                return subprocess.CompletedProcess(args, 1, "", "removal failed")
            for name, resource in list(self.live.items()):
                if resource["Id"] == args[-1] and name not in self.kept:
                    del self.live[name]
            output = args[-1]
        elif "--attach" in args:
            output = json.dumps(self.headers)
        else:
            output = args[-1]
        return subprocess.CompletedProcess(args, 0, output, "")

    def install(self, monkeypatch):
        from app.sandbox import DockerSandbox

        monkeypatch.setattr(
            DockerSandbox,
            "_run",
            lambda sandbox, *args, **kwargs: self.run(sandbox, *args, **kwargs),
        )
