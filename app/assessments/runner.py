"""Small Docker runner entry point. Credentials arrive only through stdin."""

import asyncio
import json
import sys


async def command(payload):
    if payload["op"] == "probe":
        async with asyncio.timeout(2):
            reader, writer = await asyncio.open_connection(
                payload["host"], payload["port"]
            )
            writer.close()
            await writer.wait_closed()
        return {"ready": True}
    from .http_fetch import fetch, resolve
    from .policy import PolicyError

    async with asyncio.timeout(payload["timeout"]):
        mapping = payload["mapping"]
        resolved = {name: await resolve(name) for name in set(mapping.values())}
        pinned_addresses = {host: resolved[name] for host, name in mapping.items()}

        def authorize(host, port, addresses):
            if host not in pinned_addresses or set(addresses) - set(
                pinned_addresses[host]
            ):
                raise PolicyError("connection is outside the owned Docker bundle")

        result = await fetch(
            payload["url"],
            registered=payload["registered"],
            headers=payload["headers"],
            follow_redirects=payload["follow_redirects"],
            timeout=payload["timeout"],
            authorize=authorize,
            pinned_addresses=pinned_addresses,
            ca=payload["ca"],
        )
    return {
        "observation": result["observation"].model_dump(mode="json"),
        "redirects": result["redirects"],
    }


def main():
    try:
        payload = json.load(sys.stdin)
        result = asyncio.run(command(payload))
        print(json.dumps(result))
        return 0
    except TimeoutError:
        print(
            json.dumps({"error": "runner request timed out", "error_kind": "timeout"})
        )
        return 1
    except Exception:
        # Never print exception messages or tracebacks containing runtime data.
        print(
            json.dumps(
                {"error": "runner operation failed", "error_kind": "execution_error"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
