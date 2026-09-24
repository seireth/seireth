"""Prepare disposable CI credentials shared by Compose and PostgreSQL tests."""

import os
import secrets
from pathlib import Path


def main():
    github_env = Path(os.environ["GITHUB_ENV"])
    password = secrets.token_hex(32)
    print(f"::add-mask::{password}", flush=True)
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
    with github_env.open("a", encoding="utf-8") as stream:
        stream.write(f"POSTGRES_PASSWORD={password}\n")
        stream.write(f"SEIRETH_TEST_ADMIN_URL={base_url}/postgres\n")


if __name__ == "__main__":
    main()
