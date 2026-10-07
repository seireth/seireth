"""Northstar Workspace: an in-memory web application with controlled header gaps."""

import argparse
import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import sleep
from urllib.parse import parse_qs, urlsplit

from .scenarios import BY_PATH, COOKIE_SCENARIOS, PROTECTED, SCENARIOS

STATIC = Path(__file__).parent / "static"


class WorkspaceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.ticket_lock = Lock()
        self.tickets = [
            {"id": 1, "title": "Review the release checklist", "status": "Open"},
            {
                "id": 2,
                "title": "Update the support knowledge base",
                "status": "In progress",
            },
            {"id": 3, "title": "Confirm customer onboarding", "status": "Resolved"},
        ]


def page(title, content):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | Northstar Workspace</title><link rel="stylesheet" href="/assets/app.css">
<script src="/assets/app.js" defer></script></head><body>
<header><a class="brand" href="/">N / Northstar</a><nav aria-label="Main navigation">
<a href="/">Overview</a><a href="/tickets">Tickets</a><a href="/account">Account</a><a href="/lab">Plugin lab</a>
</nav><span class="avatar" aria-label="Demo operator">DO</span></header>
<main><p class="eyebrow">NORTHSTAR WORKSPACE / OWNED DEMO</p><h1>{escape(title)}</h1>{content}</main>
<footer>Synthetic data. Tickets reset when this disposable instance stops.</footer></body></html>"""


def scenario_body(scenario):
    media_type = (scenario.content_type or "").split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        return json.dumps(
            {"scenario": scenario.name, "description": scenario.description}
        )
    if media_type == "text/css":
        return "/* Header applicability demo. */\nbody { color: #253047; }\n"
    fields = (
        "\n".join(f"{name}: {value}" for name, value in scenario.headers)
        or "No covered security headers"
    )
    expected = (
        ", ".join(scenario.expected) or "None for the checks covered by this plugin"
    )
    return page(
        scenario.name,
        f'<p class="intro">{escape(scenario.description)}</p><section class="panel"><h2>Response configuration</h2><pre>{escape(fields)}</pre><p>Expected findings: <strong>{escape(expected)}</strong></p><p>HTTP status: {scenario.status}</p><a href="/lab">Back to all scenarios</a></section>',
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "NorthstarDemo/1.0"

    def respond(
        self,
        body,
        *,
        status=200,
        headers=PROTECTED,
        content_type="text/html; charset=utf-8",
        extra=(),
    ):
        if status < 200 or status in {204, 205, 304}:
            body = b""
        body = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (*headers, *extra):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def respond_scenario(self, scenario, body, *, extra=()):
        self.respond(
            body,
            status=scenario.status,
            headers=scenario.headers,
            content_type=scenario.content_type,
            extra=extra,
        )

    def ticket_table(self):
        with self.server.ticket_lock:
            tickets = list(self.server.tickets)
        rows = "".join(
            f'<tr><td>NS-{ticket["id"]:03}</td><td>{escape(ticket["title"])}</td><td><span class="badge">{escape(ticket["status"])}</span></td></tr>'
            for ticket in tickets
        )
        return f"<table><caption>Support queue</caption><thead><tr><th>ID</th><th>Title</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/slow":
            sleep(1.5)
        scenario = BY_PATH.get(path)
        if path in {"/assets/app.css", "/assets/app.js"}:
            self.respond_scenario(
                scenario,
                (STATIC / path.rsplit("/", 1)[1]).read_bytes(),
            )
            return
        if path == "/api/tickets":
            with self.server.ticket_lock:
                body = json.dumps({"items": self.server.tickets})
            self.respond_scenario(scenario, body)
            return
        if path == "/health":
            self.respond('{"status":"ok"}', content_type="application/json")
            return
        if path == "/login":
            self.respond_scenario(
                scenario,
                page(
                    "Continue to your workspace",
                    '<p>This demo uses a synthetic operator account.</p><a href="/account">Continue</a>',
                ),
                extra=(("Location", "/account"),),
            )
            return
        if path == "/":
            content = """<p class="intro">Your team's work, ready for the next release.</p>
<section class="metrics"><article><span>Projects</span><strong>3</strong><small>Active workspaces</small></article>
<article><span>Release readiness</span><strong>92%</strong><small>Next review on Thursday</small></article>
<article><span>Support queue</span><strong id="ticket-count">3</strong><small id="api-status" role="status">Loading live queue...</small></article></section>
<section class="panel"><h2>Today's priorities</h2><p>Review your team's work and follow up on open support tickets.</p>"""
            self.respond_scenario(
                scenario,
                page(
                    "Good morning, demo operator",
                    content
                    + self.ticket_table()
                    + '<a class="button" href="/tickets">Manage tickets</a></section>',
                ),
            )
            return
        if path == "/tickets":
            content = f"""<p class="intro">Track the requests that keep your workspace moving.</p><section class="panel">{self.ticket_table()}</section>
<section class="panel"><h2>Create a ticket</h2><form action="/tickets" method="post"><label>Ticket title<input name="title" required maxlength="120" placeholder="What needs attention?"></label><button type="submit">Create ticket</button></form></section>"""
            self.respond_scenario(scenario, page("Support tickets", content))
            return
        if path == "/account":
            self.respond_scenario(
                scenario,
                page(
                    "Account settings",
                    '<section class="panel"><h2>Demo operator</h2><dl><dt>Email</dt><dd>operator@northstar.example</dd><dt>Workspace</dt><dd>Release operations</dd><dt>Role</dt><dd>Workspace administrator</dd></dl><p>This profile contains synthetic data.</p></section>',
                ),
            )
            return
        if path == "/lab":
            rows = "".join(
                f'<tr><td><a href="{scenario.path}">{escape(scenario.name)}</a><small>{escape(scenario.description)}</small></td><td>{scenario.status}</td><td>{len(scenario.expected)}</td><td>{", ".join(scenario.expected_checks)}</td></tr>'
                for scenario in (*SCENARIOS, *COOKIE_SCENARIOS)
            )
            self.respond(
                page(
                    "Plugin lab",
                    f'<p class="intro">Compare real HTTP responses with the findings and outcomes expected from the http-security-headers plugin. Outcomes are listed in order: MIME protection, CSP, framing.</p><section class="panel"><table><caption>Response scenarios</caption><thead><tr><th>Response</th><th>HTTP</th><th>Expected findings</th><th>Check outcomes</th></tr></thead><tbody>{rows}</tbody></table></section>',
                )
            )
            return
        if scenario:
            self.respond_scenario(scenario, scenario_body(scenario))
            return
        self.respond(
            page(
                "Page not found",
                '<section class="panel"><p>This page does not exist.</p><a href="/">Return to the workspace</a></section>',
            ),
            status=404,
        )

    def do_POST(self):
        path = urlsplit(self.path).path
        if path != "/tickets":
            self.respond(
                page("Page not found", "<p>This action does not exist.</p>"), status=404
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("invalid body size")
            title = (
                parse_qs(self.rfile.read(length).decode("utf-8"))
                .get("title", [""])[0]
                .strip()
            )
            if not 1 <= len(title) <= 120:
                raise ValueError("invalid title")
        except ValueError, UnicodeDecodeError:
            self.respond(
                page("Invalid ticket", "<p>Enter a title of 1 to 120 characters.</p>"),
                status=400,
            )
            return
        with self.server.ticket_lock:
            if len(self.server.tickets) >= 100:
                self.respond(
                    page("Queue full", "<p>Restart the demo to reset its tickets.</p>"),
                    status=409,
                )
                return
            self.server.tickets.append(
                {"id": len(self.server.tickets) + 1, "title": title, "status": "Open"}
            )
        self.respond("", status=303, extra=(("Location", "/tickets"),))

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    with WorkspaceServer((args.host, args.port)) as server:
        print(f"Northstar Workspace listening on {args.host}:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
