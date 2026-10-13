"""Controlled app with PostgreSQL state and a supplied bearer session."""

import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPSServer
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg


def connect():
    return psycopg.connect(
        host="postgres",
        dbname="postgres",
        user="postgres",
        password=os.environ["DATABASE_PASSWORD"],
        connect_timeout=2,
    )


with connect() as connection:
    connection.execute(
        "CREATE TABLE fixture_state (id integer PRIMARY KEY, message text NOT NULL)"
    )
    connection.execute("INSERT INTO fixture_state VALUES (1, 'seeded fixture')")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            time.sleep(60)
        if (
            self.path == "/private"
            and self.headers.get("Authorization") != os.environ["SESSION_TOKEN"]
        ):
            self.send_response(302)
            self.send_header("Location", "/login")
        else:
            with connect() as connection:
                assert (
                    connection.execute(
                        "SELECT message FROM fixture_state WHERE id=1"
                    ).fetchone()[0]
                    == "seeded fixture"
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            if self.path != "/before":
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
            self.send_header(
                "Set-Cookie", "session=fixture-response-value; Secure; HttpOnly; Path=/"
            )
            self.send_header("X-Fixture-Host", self.headers.get("Host", ""))
        self.end_headers()

    def log_message(self, *args):
        pass


with TemporaryDirectory(prefix="seireth-fixture-tls-") as directory:
    certificate = Path(directory) / "cert.pem"
    private_key = Path(directory) / "key.pem"
    certificate.write_text(os.environ["TLS_CERTIFICATE"])
    private_key.write_text(os.environ["TLS_PRIVATE_KEY"])
    private_key.chmod(0o600)
    with ThreadingHTTPSServer(
        ("0.0.0.0", 8080), Handler, certfile=certificate, keyfile=private_key
    ) as server:
        server.serve_forever()
