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

import scheduler.db_runtime as db_runtime
import scheduler.logic.admin_config as admin_logic
from scheduler.app import create_app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check database operational posture.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable summary.",
    )
    return parser


def _exit_code(payload: dict[str, object]) -> int:
    database = payload["database"]
    backup = payload["backup"]
    restore = payload["restore_drill"]

    if database.get("status") != "ok":
        return 1
    if backup.get("backup_age_state") == "error":
        return 1
    if backup.get("free_disk_state") == "error":
        return 1
    if (
        restore.get("enabled")
        and restore.get("due_now")
        and restore.get("last_status") in {"error", "never"}
    ):
        return 1
    return 0


def _render_text(payload: dict[str, object]) -> str:
    database = payload["database"]
    backup = payload["backup"]
    restore = payload["restore_drill"]
    return "\n".join(
        [
            f"database: {database.get('status')} ({database.get('latency_ms')} ms)",
            (
                "connections: "
                f"active={database.get('active_connection_count')} "
                f"lock_waits={database.get('lock_wait_count')} "
                f"idle_in_tx={database.get('idle_in_transaction_count')}"
            ),
            f"backup: {backup.get('backup_age_state')} | {backup.get('backup_age_detail')}",
            f"disk: {backup.get('free_disk_state')} | {backup.get('free_disk_detail')}",
            (
                "restore drill: "
                f"status={restore.get('last_status')} "
                f"due_now={restore.get('due_now')} "
                f"last_success={restore.get('last_success_at') or '-'}"
            ),
        ]
    )


def _startup_failure_payload(exc: Exception) -> dict[str, object]:
    return {
        "database": {
            "status": "error",
            "latency_ms": None,
            "error": exc.__class__.__name__,
            "detail": str(exc),
        },
        "backup": {
            "enabled": None,
            "backup_age_state": "unknown",
            "backup_age_detail": (
                "app startup failed before backup settings could be loaded"
            ),
            "free_disk_state": "unknown",
            "free_disk_detail": (
                "app startup failed before disk thresholds could be evaluated"
            ),
        },
        "restore_drill": {
            "enabled": None,
            "due_now": None,
            "last_status": "unknown",
            "last_success_at": "",
        },
    }


def main(argv: list[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    args = _build_parser().parse_args(cli_args)
    try:
        app = create_app(skip_startup_db_check=True)
    except Exception as exc:
        payload = _startup_failure_payload(exc)
    else:
        with app.app_context():
            payload = admin_logic.collect_admin_operations_status()
            db_runtime.dispose_database_engines()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_text(payload))

    return _exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())
