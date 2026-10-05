"""Run Seireth development commands with python -m app."""

from .cli.commands import main

if __name__ == "__main__":
    raise SystemExit(main())
