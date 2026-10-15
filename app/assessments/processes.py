"""Conservative process-exit proof for native HTTP crash recovery."""

import ctypes
import json
import os
import re
import socket
import subprocess
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path


@contextmanager
def _windows_process(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    try:
        yield kernel, handle
    finally:
        if handle:
            kernel.CloseHandle(handle)


def process_start(pid):
    try:
        if os.name != "nt":
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return fields[19]
        with _windows_process(pid) as (kernel, handle):
            if not handle:
                return None
            kernel.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                *[ctypes.POINTER(wintypes.FILETIME)] * 4,
            ]
            times = [wintypes.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(
                handle, *(ctypes.byref(value) for value in times)
            ):
                return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    except OSError, IndexError, ValueError:
        pass
    return None


def docker_json(*args):
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=2
        )
        return json.loads(result.stdout) if not result.returncode else None
    except OSError, ValueError, subprocess.TimeoutExpired:
        return None


def capture_identity():
    identity = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "start": process_start(os.getpid()),
    }
    if os.name != "nt":
        try:
            identity["namespace"] = os.stat("/proc/self/ns/pid").st_ino
            identity["boot"] = (
                Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            )
        except OSError:
            pass
        try:
            match = re.search(
                r"containers/([0-9a-f]{64})/", Path("/proc/self/mountinfo").read_text()
            )
            candidate = match[1] if match else ""
        except OSError:
            candidate = ""
        if candidate:
            records = docker_json("container", "inspect", candidate)
            daemon = docker_json("info", "--format", "{{json .ID}}")
            if records and daemon and records[0].get("State", {}).get("Running"):
                identity["container"] = {
                    "id": records[0]["Id"],
                    "started": records[0]["State"]["StartedAt"],
                    "daemon": daemon,
                }
                identity["addresses"] = [
                    address
                    for network in records[0]
                    .get("NetworkSettings", {})
                    .get("Networks", {})
                    .values()
                    for address in (
                        network.get("IPAddress"),
                        network.get("GlobalIPv6Address"),
                    )
                    if address
                ]
    return identity


def identity_exited(identity):
    if not isinstance(identity, dict) or type(identity.get("pid")) is not int:
        return False
    container = identity.get("container")
    if container:
        if (
            not isinstance(container, dict)
            or not isinstance(container.get("id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", container["id"])
            or not container.get("started")
            or not container.get("daemon")
        ):
            return False
        if docker_json("info", "--format", "{{json .ID}}") != container["daemon"]:
            return False
        records = docker_json("container", "inspect", container["id"])
        if records:
            if (
                not isinstance(records, list)
                or not isinstance(records[0], dict)
                or records[0].get("Id") != container["id"]
            ):
                return False
            state = records[0].get("State", {})
            if (
                not isinstance(state, dict)
                or type(state.get("Running")) is not bool
                or not isinstance(state.get("StartedAt"), str)
            ):
                return False
            if (
                not state.get("Running")
                or state.get("StartedAt") != container["started"]
            ):
                return True
        else:
            try:
                result = subprocess.run(
                    ["docker", "ps", "-aq", "--no-trunc"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                return (
                    not result.returncode
                    and container["id"] not in result.stdout.splitlines()
                )
            except OSError, subprocess.TimeoutExpired:
                return False
    if identity.get("host") != socket.gethostname():
        return False
    if os.name != "nt":
        try:
            if (
                identity.get("namespace") != os.stat("/proc/self/ns/pid").st_ino
                or identity.get("boot")
                != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            ):
                return False
        except OSError:
            return False
    start = process_start(identity["pid"])
    if identity.get("start") and start and start != identity["start"]:
        return True
    return process_exited(identity["pid"])


def process_exited(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        with _windows_process(pid) as (kernel, handle):
            if not handle:
                return ctypes.get_last_error() == 87
            kernel.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            status = wintypes.DWORD()
            return bool(
                kernel.GetExitCodeProcess(handle, ctypes.byref(status))
                and status.value != 259
            )
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
