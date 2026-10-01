from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            sleep(1.5)  # Owned fixture for cancellation and process-crash tests.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        if self.path == "/cookies":
            for cookie in (
                "theme=synthetic-theme; SameSite=Lax",
                "cross_site=synthetic-cross-site; SameSite=None",
                "__Secure-demo=synthetic-secure-prefix",
                "__Host-demo=synthetic-host-prefix; Secure; Domain=demo-target; Path=/app",
            ):
                self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(b"Seireth intentionally vulnerable demo target")

    def log_message(self, *_):
        pass


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
