"""Native website lifecycle. Every fetch is closed before returning to the worker."""

import asyncio
from urllib.parse import urlsplit

from ..core.config import settings
from .execution import CleanupOutcome
from .http_fetch import fetch, website_authorizer
from .policy import http_origin
from .profiles import load_config, resolve_headers


class WebsiteSession:
    def __init__(self, snapshot, context, runtime_addresses=()):
        self.snapshot, self.context = snapshot, context
        self.closed = True
        self.runtime_addresses = runtime_addresses

    def prepare(self):
        config = load_config()
        self.headers = {
            route["key"]: resolve_headers(route["request"], config)
            for route in self.snapshot["routes"]
        }

    def fetch(self, route):
        async def run():
            self.closed = False
            try:
                authorize = website_authorizer(
                    self.snapshot,
                    load_config,
                    http_origin(urlsplit(settings.api_base_url)),
                    self.runtime_addresses,
                )
                task = asyncio.create_task(
                    fetch(
                        route["url"],
                        registered=self.snapshot["target"]["url"],
                        headers=self.headers[route["key"]],
                        follow_redirects=route["request"]["follow_redirects"],
                        timeout=route["request_seconds"],
                        authorize=authorize,
                        ca=self.snapshot["ca"],
                    )
                )
                try:
                    while not task.done():
                        self.context.check()
                        await asyncio.wait({task}, timeout=0.05)
                    return await task
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                self.closed = True

        return asyncio.run(run())

    def cleanup(self):
        self.headers = {}
        return CleanupOutcome(
            self.closed, None if self.closed else "HTTP tasks have not closed"
        )
