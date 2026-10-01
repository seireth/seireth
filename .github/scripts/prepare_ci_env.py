"""Emit disposable CI credentials without reading or writing files."""

import secrets
import sys


def main():
    password = secrets.token_hex(32)
    # Keep runner commands in the log stream while stdout goes to GITHUB_ENV.
    print(f"::add-mask::{password}", file=sys.stderr, flush=True)
    base_url = f"postgresql+psycopg://seireth:{password}@127.0.0.1:5432"
    print(f"POSTGRES_PASSWORD={password}")
    print(f"SEIRETH_DATABASE_URL={base_url}/seireth")
    print(f"SEIRETH_TEST_ADMIN_URL={base_url}/postgres")


if __name__ == "__main__":
    main()
