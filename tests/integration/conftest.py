"""Real API process fixture shared by lifecycle and website recovery tests."""

import os
import socket
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from tests.integration.helpers import remove_assessment_resources


@pytest.fixture
def api_process(database, tmp_path, request, wait_until):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    backend = request.param
    env = {
        **os.environ,
        "SEIRETH_DATABASE_URL": settings.database_url,
    }
    if backend == "http":
        env["PATH"] = str(Path(sys.executable).parent)  # Docker must not be needed.
    api = SimpleNamespace(
        backend=backend, assessment_id=None, process=None, env=env, native_website=False
    )
    with ExitStack() as cleanup:
        log = cleanup.enter_context((tmp_path / "api.log").open("w+"))
        api.client = cleanup.enter_context(
            httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5)
        )

        cleanup.callback(
            lambda: (
                None
                if api.native_website
                else remove_assessment_resources(api.assessment_id)
            )
        )

        def stop(process):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            assert process.poll() is not None

        def start():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            cleanup.callback(stop, process)
            api.process = process

            def ready():
                if process.poll() is not None:
                    raise AssertionError(
                        f"API process exited with {process.returncode}"
                    )
                try:
                    return api.client.get("/health").status_code == 200
                except httpx.TransportError:
                    return False

            try:
                wait_until(
                    ready, description="API readiness", timeout=30, interval=0.05
                )
            except AssertionError as error:
                log.seek(0)
                raise AssertionError(f"{error}\n{log.read()}") from error

        api.start = start
        start()
        yield api
