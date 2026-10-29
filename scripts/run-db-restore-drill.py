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
from scheduler import model
from scheduler.app import create_app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore the latest backup into a throwaway database."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when the restore drill is disabled or not due yet.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON status instead of a human-readable summary.",
    )
    return parser


def _commit_status_updates() -> None:
    try:
        model.db.session.commit()
    except Exception:
        model.db.session.rollback()


def main(argv: list[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    args = _build_parser().parse_args(cli_args)
    app = create_app(skip_startup_db_check=True)
    with app.app_context():
        result = admin_logic.run_restore_drill_operation(
            force=args.force,
            updated_by="system",
        )
        _commit_status_updates()
        payload = result.to_payload()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            output = payload["detail"]
            if result.status == "skipped" and result.next_due_at:
                output = f"{output} (next due {result.next_due_at or 'unknown'})"
            stream = sys.stderr if result.status == "error" else sys.stdout
            print(output, file=stream)
        if result.status == "error":
            return result.exit_code or 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
