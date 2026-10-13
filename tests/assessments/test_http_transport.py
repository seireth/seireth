"""Connection pinning, redirect boundaries, TLS identity, and cancellation."""

import asyncio
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from time import monotonic

import httpcore
import pytest

from app.assessments import http_fetch
from app.assessments.execution import Cancelled, ExecutionContext
from app.assessments.plans import RoutePlan, freeze_plan
from app.assessments.policy import PolicyError
from app.assessments.website import WebsiteSession
from tests.website import configure, graph, tls_certificate


def test_unreachable_ipv6_falls_back_only_to_an_approved_ipv4_address(monkeypatch):
    connected = []

    async def resolver(host):
        return ["2001:4860:4860::8888", "1.1.1.1"]

    class Backend:
        async def connect_tcp(self, address, *args):
            connected.append(address)
            if ":" in address:
                raise httpcore.ConnectError("controlled unreachable IPv6")
            return "stream"

    monkeypatch.setattr(http_fetch, "resolve", resolver)
    backend = http_fetch.PinnedBackend(lambda *args: None)
    backend.backend = Backend()
    assert asyncio.run(backend.connect_tcp("fixture.test", 443, timeout=1)) == "stream"
    assert connected == ["2001:4860:4860::8888", "1.1.1.1"]


def test_control_interface_is_blocked_even_with_a_matching_private_grant():
    from app.assessments.profiles import OperatorConfig

    snapshot = {
        "target": {
            "url": "http://staging:8000/",
            "network_profile": "fixture",
            "trust_profile": None,
        },
        "network": {"url": "http://staging:8000/", "cidrs": ["172.18.0.0/16"]},
        "control_endpoints": [{"address": "172.18.0.2", "port": 8000}],
    }
    config = OperatorConfig(networks={"fixture": snapshot["network"]})
    authorize = http_fetch.website_authorizer(
        snapshot, lambda: config, ("http", "127.0.0.1", 9000), ["172.18.0.3"]
    )
    for address in ("172.18.0.2", "172.18.0.3", "::ffff:172.18.0.2"):
        with pytest.raises(PolicyError):
            authorize("staging", 8000, [address])
    authorize("staging", 8000, ["172.18.0.4"])


def test_dns_is_resolved_once_and_only_checked_address_is_connected(monkeypatch):
    calls = []

    async def resolver(host):
        calls.append(("resolve", host))
        return ["1.1.1.1"]

    class Backend:
        async def connect_tcp(self, address, *args):
            calls.append(("connect", address))
            return "stream"

    def authorize(host, port, addresses):
        calls.append(("authorize", host, port, addresses))

    monkeypatch.setattr(http_fetch, "resolve", resolver)
    backend = http_fetch.PinnedBackend(authorize)
    backend.backend = Backend()
    assert asyncio.run(backend.connect_tcp("fixture.test", 443)) == "stream"
    assert calls == [
        ("resolve", "fixture.test"),
        ("authorize", "fixture.test", 443, ["1.1.1.1"]),
        ("connect", "1.1.1.1"),
    ]


def test_cancelled_native_fetch_closes_tasks_before_cleanup(
    monkeypatch, tmp_path, website
):
    configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    snapshot = freeze_plan(
        project,
        target,
        [
            RoutePlan(
                key="slow", url=website.url + "slow", plugins=["http-security-headers"]
            )
        ],
    )
    cancel = Event()
    session = WebsiteSession(
        snapshot, ExecutionContext(cancel, Event(), monotonic() + 5)
    )
    session.prepare()
    errors = []

    def run():
        try:
            session.fetch(snapshot["routes"][0])
        except Cancelled:
            errors.append("cancelled")

    thread = Thread(target=run)
    thread.start()
    cancel.set()
    thread.join(timeout=5)
    assert not thread.is_alive() and errors == ["cancelled"]
    assert session.cleanup().verified


@pytest.mark.parametrize("hostname", ["fixture.test", "mismatch.test"])
def test_tls_validates_certificate_hostname_and_preserves_identity(
    monkeypatch, tmp_path, hostname
):
    cert, key = tls_certificate(tmp_path)
    names, hosts = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hosts.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.set_servername_callback(lambda sock, name, ctx: names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from types import SimpleNamespace

        from app.core.config import settings
        from app.core.identity import ACTOR

        url = f"https://{hostname}:{server.server_port}/"
        config = tmp_path / "operator.json"
        config.write_text(
            json.dumps(
                {
                    "networks": {"fixture": {"url": url, "cidrs": ["127.0.0.0/8"]}},
                    "trusts": {"fixture": {"file": str(cert)}},
                }
            )
        )
        monkeypatch.setattr(settings, "operator_config_file", str(config))

        async def resolver(host):
            assert host == hostname
            return ["127.0.0.1"]

        monkeypatch.setattr(http_fetch, "resolve", resolver)
        project = SimpleNamespace(id="project", owner_actor=ACTOR)
        target = SimpleNamespace(
            id="target",
            project_id="project",
            name="TLS fixture",
            kind="website",
            image=None,
            url=url,
            launch_profile=None,
            network_profile="fixture",
            trust_profile="fixture",
        )
        snapshot = freeze_plan(
            project,
            target,
            [RoutePlan(key="tls", url=url, plugins=["http-security-headers"])],
        )
        session = WebsiteSession(
            snapshot, ExecutionContext(Event(), Event(), monotonic() + 5)
        )
        session.prepare()
        if hostname == "fixture.test":
            assert (
                session.fetch(snapshot["routes"][0])["observation"].status_code == 200
            )
            assert hosts == [f"fixture.test:{server.server_port}"]
        else:
            with pytest.raises(httpcore.ConnectError):
                session.fetch(snapshot["routes"][0])
            assert hosts == []
        assert names == [hostname]
        assert session.cleanup().verified
        target.trust_profile = None
        untrusted = freeze_plan(
            project,
            target,
            [RoutePlan(key="tls", url=url, plugins=["http-security-headers"])],
        )
        session = WebsiteSession(
            untrusted, ExecutionContext(Event(), Event(), monotonic() + 5)
        )
        session.prepare()
        with pytest.raises(httpcore.ConnectError):
            session.fetch(untrusted["routes"][0])
        assert session.cleanup().verified
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
