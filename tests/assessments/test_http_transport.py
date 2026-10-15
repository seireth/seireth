"""Connection pinning, redirect boundaries, TLS identity, and cancellation."""

import asyncio
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from threading import Event, Thread
from time import monotonic

import dns.exception
import dns.resolver
import httpcore
import pytest

from app.assessments import http_fetch, runner, workflows
from app.assessments.execution import Cancelled, ExecutionContext
from app.assessments.plans import RoutePlan, freeze_plan
from app.assessments.policy import PolicyError
from app.assessments.website import WebsiteSession
from app.plugins.base import HttpObservation
from tests.website import configure, graph, tls_certificate


@pytest.fixture
def runner_payload():
    return {
        "op": "fetch",
        "url": "http://fixture.test/",
        "registered": "http://fixture.test/",
        "headers": {},
        "follow_redirects": False,
        "timeout": 1,
        "mapping": {"fixture.test": "target"},
        "ca": None,
    }


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


@pytest.mark.parametrize("backend", ["native", "docker"])
@pytest.mark.parametrize("cookie", [None, "session=profile-secret"])
def test_redirects_use_profile_headers_and_do_not_replay_response_cookies(
    monkeypatch, website, runner_payload, backend, cookie
):
    requests, resolutions = [], []
    origin = website.url.replace("127.0.0.1", "fixture.test")
    headers = {"Authorization": "Bearer profile-secret"}
    if cookie is not None:
        headers["Cookie"] = cookie

    def respond(handler):
        requests.append(
            (
                handler.path,
                handler.headers.get("Cookie"),
                handler.headers.get("Authorization"),
                handler.headers.get("Host"),
            )
        )
        handler.send_response(200 if handler.path == "/final" else 302)
        if handler.path != "/final":
            handler.send_header(
                "Location", "/middle" if handler.path == "/start" else "/final"
            )
        handler.send_header("Set-Cookie", "session=response-secret; Path=/")
        handler.send_header("Content-Type", "text/html")
        handler.end_headers()

    async def resolve(host):
        resolutions.append(host)
        assert host == ("target" if backend == "docker" else "fixture.test")
        return ["127.0.0.1"]

    monkeypatch.setattr(website.handler, "do_GET", respond)
    monkeypatch.setattr(http_fetch, "resolve", resolve)
    if backend == "docker":
        response = asyncio.run(
            runner.command(
                runner_payload
                | {
                    "url": origin + "start",
                    "registered": origin,
                    "headers": headers,
                    "follow_redirects": True,
                }
            )
        )
        observation = HttpObservation.model_validate(response["observation"])
    else:
        response = asyncio.run(
            http_fetch.fetch(
                origin + "start",
                registered=origin,
                headers=headers,
                follow_redirects=True,
                authorize=lambda *args: None,
            )
        )
        observation = response["observation"]
    assert requests == [
        (path, cookie, "Bearer profile-secret", origin.split("//")[1].rstrip("/"))
        for path in ("/start", "/middle", "/final")
    ]
    assert resolutions == (["target"] if backend == "docker" else ["fixture.test"] * 3)
    assert observation.headers["set-cookie"] == ["session=response-secret; Path=/"]
    assert len(response["redirects"]) == 2


def test_runner_dns_resolution_obeys_route_deadline(monkeypatch, runner_payload):
    cancelled = []

    async def resolve(host):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
        return ["127.0.0.1"]

    async def fetch(*args, **kwargs):
        pytest.fail("an expired DNS budget must not start an HTTP request")

    monkeypatch.setattr(http_fetch, "resolve", resolve)
    monkeypatch.setattr(http_fetch, "fetch", fetch)
    with pytest.raises(TimeoutError):
        asyncio.run(runner.command(runner_payload | {"timeout": 0.01}))
    assert cancelled == [True]


def test_runner_dns_and_http_share_one_deadline(monkeypatch, runner_payload):
    fetched = []

    async def resolve(host):
        await asyncio.sleep(0.05)
        return ["127.0.0.1"]

    async def fetch(url, **kwargs):
        fetched.append(url)
        await asyncio.sleep(0.17)
        return {
            "observation": HttpObservation(url=url, status_code=200, headers={}),
            "redirects": [],
        }

    monkeypatch.setattr(http_fetch, "resolve", resolve)
    monkeypatch.setattr(http_fetch, "fetch", fetch)
    with pytest.raises(TimeoutError):
        asyncio.run(runner.command(runner_payload | {"timeout": 0.2}))
    assert fetched == [runner_payload["url"]]


@pytest.mark.parametrize("pinned", [{}, {"fixture.test": []}])
def test_missing_pinned_addresses_cannot_fall_back_to_dns(monkeypatch, pinned):
    async def resolve(host):
        pytest.fail("an owned bundle must use only its pinned addresses")

    monkeypatch.setattr(http_fetch, "resolve", resolve)
    backend = http_fetch.PinnedBackend(lambda *args: None, pinned)
    with pytest.raises(PolicyError, match="no approved addresses"):
        asyncio.run(backend.connect_tcp("fixture.test", 80))


def test_pinned_addresses_are_authorized_before_every_connection(monkeypatch):
    authorized, connected = [], []

    def authorize(host, port, addresses):
        authorized.append((host, port, addresses))
        if len(authorized) > 1:
            raise PolicyError("permission revoked")

    async def connect(address, *args):
        connected.append(address)
        return "stream"

    backend = http_fetch.PinnedBackend(authorize, {"fixture.test": ["127.0.0.1"]})
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)

    async def run():
        assert await backend.connect_tcp("fixture.test", 80) == "stream"
        with pytest.raises(PolicyError, match="permission revoked"):
            await backend.connect_tcp("fixture.test", 80)

    asyncio.run(run())
    assert authorized == [("fixture.test", 80, ["127.0.0.1"])] * 2
    assert connected == ["127.0.0.1"]


@pytest.mark.parametrize(
    "failure,expected,message",
    [
        (dns.exception.Timeout, TimeoutError, "destination DNS resolution timed out"),
        (
            dns.resolver.LifetimeTimeout,
            TimeoutError,
            "destination DNS resolution timed out",
        ),
        (dns.resolver.NXDOMAIN, PolicyError, "destination DNS resolution failed"),
    ],
)
def test_dns_failures_preserve_classification_and_redact_diagnostics(
    monkeypatch, failure, expected, message
):
    async def resolve_name(*args, **kwargs):
        raise failure("sensitive DNS diagnostic")

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve_name", resolve_name)
    with pytest.raises(expected) as error:
        asyncio.run(http_fetch.resolve("fixture.test"))
    assert str(error.value) == message


def test_dns_timeout_is_reported_by_native_workflow(
    monkeypatch, tmp_path, website, execution_context
):
    configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    target.url, target.network_profile = "http://fixture.test/", None
    snapshot = freeze_plan(
        project,
        target,
        [RoutePlan(key="root", url=target.url, plugins=["http-security-headers"])],
    )

    async def resolve_name(*args, **kwargs):
        raise dns.resolver.LifetimeTimeout("sensitive DNS diagnostic")

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve_name", resolve_name)
    records = []
    outcome = workflows.execute_plan(
        WebsiteSession(snapshot, execution_context),
        snapshot,
        execution_context,
        lambda data, results: records.append(data),
    )
    assert outcome.error_kind == records[0]["error_kind"] == "timeout"
    assert outcome.cleanup_verified
    assert "sensitive DNS diagnostic" not in json.dumps(records)


def test_dns_timeout_is_reported_by_docker_runner(monkeypatch, capsys, runner_payload):
    async def resolve_name(*args, **kwargs):
        raise dns.resolver.LifetimeTimeout("sensitive DNS diagnostic")

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve_name", resolve_name)
    monkeypatch.setattr(runner.sys, "stdin", StringIO(json.dumps(runner_payload)))
    assert runner.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "error": "runner request timed out",
        "error_kind": "timeout",
    }
    assert captured.err == ""


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
