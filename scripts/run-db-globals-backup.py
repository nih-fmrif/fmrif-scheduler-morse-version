#!/usr/bin/env python3
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scheduler.runtime_scope import apply_runtime_scope_database_env

apply_runtime_scope_database_env()

import scheduler.logic.admin_config as admin_logic
from scheduler.app import create_app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a companion PostgreSQL globals backup."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Accepted for interface compatibility; globals backups are operator-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON status instead of a human-readable summary.",
    )
    parser.add_argument(
        "--owner-user",
        default="",
        help="Chown the globals backup artifact to this user after creation.",
    )
    parser.add_argument(
        "--owner-group",
        default="",
        help="Chown the globals backup artifact to this group after creation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    args = _build_parser().parse_args(cli_args)
    app = create_app(skip_startup_db_check=True)
    with app.app_context():
        result = admin_logic.run_globals_backup_operation(
            force=args.force,
            updated_by="system",
            owner_user=args.owner_user,
            owner_group=args.owner_group,
        )
        payload = result.to_payload()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            output = payload["detail"]
            stream = sys.stderr if result.status == "error" else sys.stdout
            print(output, file=stream)
        if result.status == "error":
            return result.exit_code or 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
