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
from scheduler.app import create_app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check database reachability.")
    parser.add_argument(
        "--database-only",
        action="store_true",
        help=(
            "Deprecated compatibility flag. This command now checks database "
            "reachability only."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable summary.",
    )
    return parser


def _render_text(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"database: {payload.get('status')} ({payload.get('latency_ms')} ms)",
            (
                "connections: "
                f"active={payload.get('active_connection_count')} "
                f"lock_waits={payload.get('lock_wait_count')} "
                f"idle_in_tx={payload.get('idle_in_transaction_count')}"
            ),
        ]
    )


def _startup_failure_payload(exc: Exception) -> dict[str, object]:
    return {
        "status": "error",
        "latency_ms": None,
        "error": exc.__class__.__name__,
        "detail": str(exc),
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
            payload = db_runtime.probe_database_health()
            db_runtime.dispose_database_engines()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_text(payload))

    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
