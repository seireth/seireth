"""Controlled website fixture and operator configuration shared across test layers."""

import json
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from types import SimpleNamespace

import pytest

from app.core.config import settings


def tls_certificate(directory, hostname="fixture.test"):
    executable = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"
    if not Path(executable).is_file():
        pytest.skip("openssl required to generate a controlled local certificate")
    certificate, private_key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-noenc",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            f"/CN={hostname}",
            "-addext",
            f"subjectAltName=DNS:{hostname}",
        ],
        capture_output=True,
        check=True,
    )
    return certificate, private_key


@pytest.fixture
def website():
    class Handler(BaseHTTPRequestHandler):
        requests = []
        corrected = False

        def do_GET(self):
            type(self).requests.append(
                (self.path, self.headers.get("Authorization"), self.headers.get("Host"))
            )
            if self.path == "/slow":
                sleep(0.5)
            if (
                self.path == "/private"
                and self.headers.get("Authorization") != "Bearer fixture-secret"
            ):
                self.send_response(302)
                self.send_header("Location", "/login")
            else:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json" if self.path == "/api" else "text/html",
                )
                if self.corrected:
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'none'; frame-ancestors 'none'",
                    )
                else:
                    self.send_header(
                        "Content-Security-Policy",
                        "script-src https: 'unsafe-inline' 'unsafe-eval'",
                    )
                if self.path == "/session":
                    self.send_header("Set-Cookie", "session=response-secret; Path=/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}/", handler=Handler
    )
    server.shutdown()
    server.server_close()
    thread.join()


def configure(monkeypatch, tmp_path, website):
    path = tmp_path / "operator.json"
    path.write_text(
        json.dumps(
            {
                "networks": {"fixture": {"url": website.url, "cidrs": ["127.0.0.0/8"]}},
                "secrets": {"session": {"env": "FIXTURE_SESSION"}},
                "requests": {
                    "authenticated": {"secret_headers": {"Authorization": "session"}}
                },
            }
        )
    )
    monkeypatch.setattr(settings, "operator_config_file", str(path))
    monkeypatch.setenv("FIXTURE_SESSION", "Bearer fixture-secret")
    return path


def graph(website):
    from app.core.identity import ACTOR

    return SimpleNamespace(id="project", owner_actor=ACTOR), SimpleNamespace(
        id="target",
        project_id="project",
        name="fixture",
        kind="website",
        image=None,
        url=website.url,
        network_profile="fixture",
        trust_profile=None,
        launch_profile=None,
    )
