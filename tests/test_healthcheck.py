from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.healthcheck import healthy


@pytest.mark.parametrize("statuses", [[503, 503, 200], [503, 503, 503], [500], [204]])
def test_health_probe_requires_http_200(statuses):
    current = [503]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/health"
            self.send_response(current[0])
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/health"
    try:
        for status in statuses:
            current[0] = status
            assert healthy(url) is (status == 200)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert not healthy(url)  # An exited API cannot be healthy.


def test_health_probe_has_bounded_request_timeout(monkeypatch):
    def timeout(url, *, timeout):
        assert timeout == 2
        raise TimeoutError("unresponsive API")

    monkeypatch.setattr("app.healthcheck.urlopen", timeout)
    assert not healthy()
