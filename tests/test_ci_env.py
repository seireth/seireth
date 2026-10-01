"""Check CI credential generation and its filesystem boundary."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/prepare_ci_env.py"


@pytest.mark.parametrize("github_env", [None, "../outside.env"])
def test_prepare_ci_env_emits_credentials_without_opening_github_env(
    tmp_path, github_env
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env.example").write_text(
        "# Preserve configuration\n"
        "SEIRETH_API_PORT=8000\n"
        "POSTGRES_PASSWORD=old-password\n"
        "SEIRETH_DATABASE_URL=old-url\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside.env"
    outside.write_text("existing content\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("GITHUB_ENV", None)
    if github_env is not None:
        environment["GITHUB_ENV"] = github_env

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    exported = dict(line.split("=", 1) for line in result.stdout.splitlines())
    password = exported["POSTGRES_PASSWORD"]
    assert re.fullmatch(r"[0-9a-f]{64}", password)
    base_url = f"postgresql+psycopg://seireth:{password}@127.0.0.1:5432"
    assert exported == {
        "POSTGRES_PASSWORD": password,
        "SEIRETH_TEST_ADMIN_URL": f"{base_url}/postgres",
    }
    assert result.stderr == f"::add-mask::{password}\n"
    assert (workspace / ".env").read_text(encoding="utf-8") == (
        "# Preserve configuration\n"
        "SEIRETH_API_PORT=8000\n"
        f"POSTGRES_PASSWORD={password}\n"
        f"SEIRETH_DATABASE_URL={base_url}/seireth\n"
    )
    assert outside.read_text(encoding="utf-8") == "existing content\n"
