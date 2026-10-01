"""Check CI credential generation and its filesystem boundary."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/prepare_ci_env.py"


@pytest.mark.parametrize(
    "github_env,existing_config", [(None, False), ("../outside.env", True)]
)
def test_prepare_ci_env_emits_credentials_without_file_access(
    tmp_path, github_env, existing_config
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Invalid UTF-8 proves credential generation does not read either file.
    original_config = b"\xffexisting configuration\n"
    if existing_config:
        for name in (".env.example", ".env"):
            (workspace / name).write_bytes(original_config)
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
        "SEIRETH_DATABASE_URL": f"{base_url}/seireth",
        "SEIRETH_TEST_ADMIN_URL": f"{base_url}/postgres",
    }
    assert result.stderr == f"::add-mask::{password}\n"
    if existing_config:
        for name in (".env.example", ".env"):
            assert (workspace / name).read_bytes() == original_config
    else:
        assert not list(workspace.iterdir())
    assert outside.read_text(encoding="utf-8") == "existing content\n"


def test_prepare_ci_env_generates_fresh_credentials_each_run(tmp_path):
    passwords = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        exported = dict(line.split("=", 1) for line in result.stdout.splitlines())
        password = exported["POSTGRES_PASSWORD"]
        assert re.fullmatch(r"[0-9a-f]{64}", password)
        assert result.stderr == f"::add-mask::{password}\n"
        passwords.append(password)
    assert passwords[0] != passwords[1]
    assert not list(tmp_path.iterdir())
