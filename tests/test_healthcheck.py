from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.healthcheck import healthy


def test_health_probe_requires_http_200_and_rejects_exited_api():
    current = [503]
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(current[0])
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/health"
    try:
        for status in (200, 503, 500, 204):
            current[0] = status
            assert healthy(url) is (status == 200)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert paths == ["/health"] * 4
    assert not thread.is_alive()
    assert not healthy(url)  # An exited API cannot be healthy.


def test_health_probe_has_bounded_request_timeout(monkeypatch):
    def timeout(url, *, timeout):
        assert timeout == 2
        raise TimeoutError("unresponsive API")

    monkeypatch.setattr("app.healthcheck.urlopen", timeout)
    assert not healthy()
