"""Prepare disposable CI credentials shared by Compose and PostgreSQL tests."""

import secrets
import sys
from pathlib import Path


def main():
    password = secrets.token_hex(32)
    # Keep runner commands in the log stream while stdout goes to GITHUB_ENV.
    print(f"::add-mask::{password}", file=sys.stderr, flush=True)
    base_url = f"postgresql+psycopg://seireth:{password}@127.0.0.1:5432"
    overrides = {
        "POSTGRES_PASSWORD": password,
        "SEIRETH_DATABASE_URL": f"{base_url}/seireth",
    }
    lines = [
        line
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
        if line.partition("=")[0] not in overrides
    ]
    lines.extend(f"{key}={value}" for key, value in overrides.items())
    Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"POSTGRES_PASSWORD={password}")
    print(f"SEIRETH_TEST_ADMIN_URL={base_url}/postgres")


if __name__ == "__main__":
    main()
