"""Compose readiness probe, independent of operator settings and the database."""

from urllib.request import urlopen


def healthy(url="http://127.0.0.1:8000/health") -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
