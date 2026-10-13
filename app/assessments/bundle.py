"""Owned Docker service bundles using the existing command/ownership guards."""

import json
from copy import deepcopy
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ..core.config import settings
from ..plugins.base import HttpObservation
from .profiles import (
    dependency_order,
    load_config,
    resolve_headers,
    resolve_secret,
)
from .sandbox import _RESOURCE_ID, CleanupOutcome, DockerCommands


def new_bundle_journal(snapshot, attempt_id):
    token = attempt_id.replace("-", "")
    entries = {"network": "network", "runner": "container", "target": "container"}
    launch = snapshot["launch"]
    entries.update({name: "container" for name in launch["services"]})
    volumes = [
        volume
        for spec in [launch["target"], *launch["services"].values()]
        for volume in spec["volumes"]
    ]
    if volumes:
        entries["initializer"] = "container"
    entries.update({f"volume-{volume['name']}": "volume" for volume in volumes})
    return {
        "version": 1,
        "owner": str(uuid4()),
        "resources": {
            key: {
                "kind": kind,
                "name": f"seireth-{key}-{token}",
                "state": "not_requested",
                "id": None,
            }
            for key, kind in entries.items()
        },
    }


class BundleSession(DockerCommands):
    def __init__(self, snapshot, attempt, *, persist_journal, context=None):
        self.snapshot = snapshot
        self.context = context
        self.assessment_id, self.attempt_id = attempt.assessment_id, attempt.id
        self.journal = deepcopy(attempt.operation_journal)
        self.resources = {
            key: entry["name"] for key, entry in self.journal["resources"].items()
        }
        self.persist_journal = persist_journal
        self.command_timeout = settings.docker_timeout_seconds

    def _run(self, args, timeout, **kwargs):
        deadline = getattr(self, "_cleanup_deadline", None)
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("cleanup budget exceeded")
            timeout = min(timeout, remaining)
        return super()._run(args, timeout, **kwargs)

    def _record(self, key, state, identity=None, *, advancing=False, created_at=None):
        journal = deepcopy(self.journal)
        entry = journal["resources"][key]
        entry.update(state=state, id=identity)
        if created_at:
            entry["created_at"] = created_at
        self.persist_journal(journal, advancing=advancing)
        self.journal = journal

    def _create(self, key, args, extra_env=None):
        self._record(key, "uncertain", advancing=True)
        result = self._run(args, self.command_timeout, extra_env=extra_env)
        if result.returncode:
            raise RuntimeError("Docker bundle resource creation failed")
        identity = result.stdout.strip()
        kind = self.journal["resources"][key]["kind"]
        if kind == "volume":
            inspected = self._inspect(key)
            if not inspected:
                raise RuntimeError("volume creation could not be verified")
            self._record(
                key,
                "created",
                identity,
                advancing=True,
                created_at=inspected["CreatedAt"],
            )
        else:
            if not _RESOURCE_ID.fullmatch(identity):
                raise RuntimeError("Docker returned an invalid resource identity")
            self._record(key, "created", identity, advancing=True)
        return identity

    def _labels(self):
        return [
            arg
            for name, value in self.labels.items()
            for arg in ("--label", f"{name}={value}")
        ]

    def _restricted(self, spec):
        return [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={spec['memory']}",
            f"--cpus={spec['cpus']}",
            f"--pids-limit={spec['pids']}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            f"--user={spec['uid']}:{spec['gid']}",
        ] + [f"--tmpfs={path}:rw,noexec,nosuid,size=16m" for path in spec["tmpfs"]]

    def _start(self, key, args=None):
        result = self._run(
            ["start", *(args or []), self.journal["resources"][key]["id"]],
            self.command_timeout,
        )
        if result.returncode:
            raise RuntimeError("Docker bundle startup failed")

    def _mounts(self, volumes):
        return [
            arg
            for volume in volumes
            for arg in (
                "--mount",
                f"type=volume,source={self.resources['volume-' + volume['name']]},target={volume['path']},volume-nocopy",
            )
        ]

    def _runner(self, payload, timeout):
        result = self._run(
            [
                "exec",
                "-i",
                self.resources["runner"],
                "python",
                "-m",
                "app.assessments.runner",
            ],
            timeout,
            input_data=json.dumps(payload),
        )
        try:
            value = json.loads(result.stdout)
            if result.returncode:
                if value.get("error_kind") == "timeout":
                    raise TimeoutError("Docker runner request timed out")
                raise RuntimeError("Docker runner operation failed")
            return value
        except ValueError:
            raise RuntimeError("Docker runner response is invalid") from None

    def prepare(self):
        config = load_config()
        self.headers = {
            route["key"]: resolve_headers(route["request"], config)
            for route in self.snapshot["routes"]
        }
        launch = self.snapshot["launch"]
        specs = {**launch["services"], "target": launch["target"]}
        # Resolve every dependency before requesting the first Docker resource.
        environment = {
            name: {
                **spec["environment"],
                **{
                    key: resolve_secret(ref, config)
                    for key, ref in spec["secret_environment"].items()
                },
            }
            for name, spec in specs.items()
        }
        startup_deadline = monotonic() + launch["startup_seconds"]
        self._create(
            "network",
            [
                "network",
                "create",
                "--internal",
                *self._labels(),
                self.resources["network"],
            ],
        )
        initialization = []
        for spec in specs.values():
            for volume in spec["volumes"]:
                key = f"volume-{volume['name']}"
                self._create(
                    key, ["volume", "create", *self._labels(), self.resources[key]]
                )
                initialization.append(
                    {
                        "name": volume["name"],
                        "path": f"/volumes/{volume['name']}",
                        "uid": spec["uid"],
                        "gid": spec["gid"],
                    }
                )
        if initialization:
            self._initialize_volumes(initialization, self._mounts(initialization))
        runner_spec = {
            **self.snapshot["runner_limits"],
            "uid": 65532,
            "gid": 65532,
            "tmpfs": [],
        }
        self._create(
            "runner",
            [
                "create",
                "--pull=never",
                "--name",
                self.resources["runner"],
                "--network",
                self.resources["network"],
                *self._labels(),
                *self._restricted(runner_spec),
                "--entrypoint=python",
                self.snapshot["images"]["runner"],
                "-c",
                "import time; time.sleep(86400)",
            ],
        )
        self._start("runner")
        for name in dependency_order(
            {name: spec["depends_on"] for name, spec in specs.items()}
        ):
            spec = specs[name]
            env_args = [arg for key in environment[name] for arg in ("--env", key)]
            self._create(
                name,
                [
                    "create",
                    "--pull=never",
                    "--name",
                    self.resources[name],
                    "--network",
                    self.resources["network"],
                    "--network-alias",
                    name,
                    *self._labels(),
                    *self._restricted(spec),
                    *env_args,
                    *self._mounts(spec["volumes"]),
                    self.snapshot["images"][name],
                    *spec["command"],
                ],
                extra_env=environment[name],
            )
            self._start(name)
            self._ready(name, spec, startup_deadline)

    def _initialize_volumes(self, volumes, mounts):
        payload = json.dumps(volumes)
        self._create(
            "initializer",
            [
                "create",
                "--pull=never",
                "--name",
                self.resources["initializer"],
                "--network=none",
                *self._labels(),
                "--read-only",
                "--cap-drop=ALL",
                "--cap-add=CHOWN",
                "--security-opt=no-new-privileges",
                "--user=0:0",
                "--memory=64m",
                "--pids-limit=16",
                *mounts,
                "--env",
                "SEIRETH_VOLUME_INIT",
                "--entrypoint=python",
                self.snapshot["images"]["runner"],
                "-c",
                "import json,os; [os.chown(v['path'],v['uid'],v['gid']) for v in json.loads(os.environ['SEIRETH_VOLUME_INIT'])]",
            ],
            extra_env={"SEIRETH_VOLUME_INIT": payload},
        )
        self._start("initializer", ["--attach"])

    def _ready(self, name, spec, deadline):
        probe = spec["readiness"]
        if probe is None:
            return
        while monotonic() < deadline:
            self.context.check()
            try:
                # Include interpreter startup, as route requests do, while keeping
                # the whole readiness operation inside the startup budget.
                command_seconds = min(7, deadline - monotonic())
                if probe["kind"] == "tcp":
                    self._runner(
                        {"op": "probe", "host": name, "port": probe["port"]},
                        command_seconds,
                    )
                else:
                    host = (
                        urlsplit(self.snapshot["target"]["url"]).hostname
                        if name == "target"
                        else name
                    )
                    origin = httpx.URL(
                        scheme=probe["kind"], host=host, port=probe["port"]
                    )
                    value = self._runner(
                        {
                            "op": "fetch",
                            "url": str(origin) + probe["path"],
                            "registered": str(origin.copy_with(path="/")),
                            "headers": {},
                            "follow_redirects": False,
                            "timeout": 2,
                            "mapping": {host: name},
                            "ca": self.snapshot["ca"],
                        },
                        command_seconds,
                    )
                    if value["observation"]["status_code"] != probe["status"]:
                        raise RuntimeError("readiness status mismatch")
                return
            except RuntimeError, TimeoutError:
                sleep(0.1)
        raise TimeoutError("Docker bundle readiness timed out")

    def fetch(self, route):
        host = urlsplit(self.snapshot["target"]["url"]).hostname
        value = self._runner(
            {
                "op": "fetch",
                "url": route["url"],
                "registered": self.snapshot["target"]["url"],
                "headers": self.headers[route["key"]],
                "follow_redirects": route["request"]["follow_redirects"],
                "timeout": route["request_seconds"],
                "mapping": {host: "target"},
                "ca": self.snapshot["ca"],
            },
            route["request_seconds"] + 5,
        )
        return {
            "observation": HttpObservation.model_validate(value["observation"]),
            "redirects": value["redirects"],
        }

    def _inspect(self, key):
        entry = self.journal["resources"][key]
        kind = entry["kind"]
        command = (
            ["ps", "-a", "--format", "{{.Names}}"]
            if kind == "container"
            else [kind, "ls", "--format", "{{.Name}}"]
        )
        listed = self._run(command, self.command_timeout, interruptible=False)
        if listed.returncode:
            raise RuntimeError("resource enumeration failed")
        if entry["name"] not in listed.stdout.splitlines():
            return None
        result = self._run(
            [kind, "inspect", entry["name"]], self.command_timeout, interruptible=False
        )
        if result.returncode:
            raise RuntimeError("resource inspection failed")
        record = json.loads(result.stdout)[0]
        labels = (
            record.get("Config", {}).get("Labels")
            if kind == "container"
            else record.get("Labels")
        )
        if not labels or any(
            labels.get(name) != value for name, value in self.labels.items()
        ):
            raise RuntimeError("resource ownership mismatch")
        identity = record.get("Name") if kind == "volume" else record.get("Id")
        if entry["id"] and entry["id"] != identity:
            raise RuntimeError("resource identity mismatch")
        if (
            kind == "volume"
            and entry["id"] is not None
            and entry["created_at"] != record.get("CreatedAt")
        ):
            raise RuntimeError("volume creation identity mismatch")
        return record

    def cleanup(self):
        self.headers = {}
        reasons = []
        deadline = monotonic() + self.snapshot["cleanup_seconds"]
        self._cleanup_deadline = deadline
        keys = sorted(
            self.resources,
            key=lambda key: {"container": 0, "volume": 1, "network": 2}[
                self.journal["resources"][key]["kind"]
            ],
        )
        for key in keys:
            entry = self.journal["resources"][key]
            if entry["state"] == "not_requested":
                continue
            if monotonic() >= deadline:
                reasons.append(f"{key}: cleanup budget exceeded")
                continue
            try:
                self._guard()
                record = self._inspect(key)
                if record:
                    identity = (
                        record.get("Name")
                        if entry["kind"] == "volume"
                        else record.get("Id")
                    )
                    self._record(
                        key, "created", identity, created_at=record.get("CreatedAt")
                    )
                    args = (
                        ["rm", "-f", identity]
                        if entry["kind"] == "container"
                        else [entry["kind"], "rm", identity]
                    )
                    self._run(args, self.command_timeout, interruptible=False)
                if self._inspect(key):
                    reasons.append(f"{key}: removal not verified")
                elif self.journal["resources"][key]["state"] == "uncertain":
                    reasons.append(f"{key}: creation outcome unknown")
                else:
                    self._record(key, "removed", self.journal["resources"][key]["id"])
            except Exception:
                reasons.append(f"{key}: cleanup could not be verified")
        return CleanupOutcome(not reasons, "; ".join(reasons) or None)
