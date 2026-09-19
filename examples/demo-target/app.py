from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            sleep(1.5)  # Owned fixture for cancellation and process-crash tests.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Seireth intentionally vulnerable demo target")

    def log_message(self, *_):
        pass


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
