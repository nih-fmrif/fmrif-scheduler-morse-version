#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg2
import requests
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import create_engine

from scheduler.runtime_scope import (
    DEFAULT_APP_PORT,
    DEFAULT_DATABASE_ENV,
    resolve_scoped_runtime_values,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PG_IDENTIFIER_MAX_LENGTH = 63
_REHEARSAL_DB_SUFFIX = "_deployment_rehearsal"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse the supported initial-deployment flow: SQL bootstrap, "
            "Alembic stamping/verification, and app smoke checks."
        )
    )
    parser.add_argument(
        "--database",
        default="",
        help=(
            "Target database name for the rehearsal. Defaults to a dedicated "
            "scratch database derived from the configured PGDATABASE."
        ),
    )
    parser.add_argument(
        "--seed-file",
        default="sql/003-import-data.sql",
        help="003-contract seed dump to bootstrap from.",
    )
    parser.add_argument(
        "--additive-layer",
        action="append",
        default=[],
        help=(
            "Additive layer SQL file to run after bootstrap. Repeatable. "
            "Defaults to sql/900-import-new-data.sql unless --skip-additive-layer is set."
        ),
    )
    parser.add_argument(
        "--skip-additive-layer",
        action="store_true",
        help="Disable additive layer execution during bootstrap.",
    )
    parser.add_argument(
        "--skip-app-smoke",
        action="store_true",
        help="Skip temporary local app startup and HTTP smoke checks.",
    )
    parser.add_argument(
        "--smoke-timeout-seconds",
        type=int,
        default=90,
        help="Timeout for temporary app startup and smoke checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON only.",
    )
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    return parser.parse_args(argv)


def derive_rehearsal_database_name(configured_database: str) -> str:
    raw_name = configured_database.strip() or DEFAULT_DATABASE_ENV["PGDATABASE"]
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw_name.lower()).strip("_")
    if not normalized:
        normalized = DEFAULT_DATABASE_ENV["PGDATABASE"]
    max_base_length = _PG_IDENTIFIER_MAX_LENGTH - len(_REHEARSAL_DB_SUFFIX)
    return f"{normalized[:max_base_length]}{_REHEARSAL_DB_SUFFIX}"


def resolve_runtime_env(args: argparse.Namespace) -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    env = os.environ.copy()
    defaults = {**DEFAULT_DATABASE_ENV, "APP_PORT": DEFAULT_APP_PORT}
    scoped_values = resolve_scoped_runtime_values(defaults, environ=env)
    base_values = resolve_scoped_runtime_values(
        defaults,
        environ=env,
        scoped_port_names=frozenset(),
    )
    env["PGHOST"] = scoped_values["PGHOST"]
    env["PGPORT"] = scoped_values["PGPORT"]
    env["PGUSER"] = scoped_values["PGUSER"]
    env["PGPASSWORD"] = scoped_values["PGPASSWORD"]
    configured_database = scoped_values["PGDATABASE"]
    env["PGDATABASE"] = args.database or derive_rehearsal_database_name(
        configured_database
    )
    env["REHEARSAL_SOURCE_DATABASE"] = configured_database
    env["BASE_PGPORT"] = base_values["PGPORT"]
    env["BASE_APP_PORT"] = base_values["APP_PORT"]
    env["APP_PORT"] = scoped_values["APP_PORT"]
    env["FMRIF_RUNTIME_SCOPE_OFFSET"] = scoped_values["FMRIF_RUNTIME_SCOPE_OFFSET"]
    env.setdefault("APP_SERVER", "gunicorn")
    return env


def resolve_repo_path(raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def run_command(
    cmd: list[str],
    *,
    env: dict[str, str],
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=capture_output,
        check=True,
    )


def connect(env: dict[str, str], *, database: str | None = None):
    return psycopg2.connect(
        host=env["PGHOST"],
        port=int(env["PGPORT"]),
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        dbname=database or env["PGDATABASE"],
        connect_timeout=5,
    )


def sqlalchemy_database_url(env: dict[str, str], *, database: str | None = None) -> str:
    return (
        f"postgresql+psycopg2://{quote(env['PGUSER'])}:{quote(env['PGPASSWORD'])}"
        f"@{env['PGHOST']}:{env['PGPORT']}/{quote(database or env['PGDATABASE'])}"
    )


def query_one(env: dict[str, str], sql: str) -> Any:
    with connect(env) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return None if row is None else row[0]


def collect_bootstrap_snapshot(env: dict[str, str]) -> dict[str, Any]:
    with connect(env) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    to_regclass('public.tlkpresearcher') is not null,
                    to_regclass('public.tbltemplate') is not null,
                    to_regclass('public.site_sessions') is not null,
                    to_regclass('public.oauth_state') is not null,
                    to_regclass('public.app_settings') is not null,
                    to_regclass('public.alembic_version') is not null,
                    (select count(*) from tlkpresearcher),
                    (select count(*) from tbltemplate)
                """
            )
            row = cur.fetchone()
            assert row is not None
    return {
        "has_users_table": bool(row[0]),
        "has_template_table": bool(row[1]),
        "has_site_sessions_table": bool(row[2]),
        "has_oauth_state_table": bool(row[3]),
        "has_app_settings_table": bool(row[4]),
        "has_alembic_version_table": bool(row[5]),
        "researcher_rows": int(row[6]),
        "template_rows": int(row[7]),
    }


def bootstrap_database(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    bootstrap_env = env.copy()
    bootstrap_env["DROP_DB"] = "true"
    bootstrap_env["SQL_SEED_DUMP_FILE"] = resolve_repo_path(args.seed_file)

    if args.skip_additive_layer:
        bootstrap_env["SQL_ADDITIVE_LAYER_FILES"] = ""
    else:
        layers = args.additive_layer or ["sql/900-import-new-data.sql"]
        bootstrap_env["SQL_ADDITIVE_LAYER_FILES"] = ",".join(
            resolve_repo_path(layer) for layer in layers
        )

    run_command(
        ["bash", str(PROJECT_ROOT / "sql" / "000-init.sh")],
        env=bootstrap_env,
        capture_output=False,
    )
    snapshot = collect_bootstrap_snapshot(bootstrap_env)
    if not snapshot["has_users_table"] or not snapshot["has_template_table"]:
        raise RuntimeError(
            f"Bootstrap did not produce the expected core tables: {snapshot}"
        )
    if snapshot["researcher_rows"] <= 0 or snapshot["template_rows"] <= 0:
        raise RuntimeError(
            f"Bootstrap produced empty core data unexpectedly: {snapshot}"
        )
    return snapshot


@contextlib.contextmanager
def temporary_environment(env: dict[str, str]):
    keys = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = env[key]
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def alembic_head_revision() -> str:
    config = Config(toml_file=str(PROJECT_ROOT / "pyproject.toml"))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def stamp_and_verify_alembic(env: dict[str, str]) -> dict[str, Any]:
    head_revision = alembic_head_revision()
    config = Config(toml_file=str(PROJECT_ROOT / "pyproject.toml"))

    with temporary_environment(env):
        command.stamp(config, head_revision)

    engine = create_engine(sqlalchemy_database_url(env))
    try:
        with engine.connect() as connection:
            current_revision = MigrationContext.configure(
                connection
            ).get_current_revision()
    finally:
        engine.dispose()
    version_num = query_one(env, "select version_num from alembic_version")
    if version_num != head_revision:
        raise RuntimeError(
            "Stamped alembic_version does not match head revision: "
            f"version_num={version_num!r} head={head_revision!r}"
        )
    if current_revision != head_revision:
        raise RuntimeError(
            "Current Alembic revision does not match the stamped head revision: "
            f"current_revision={current_revision!r} head={head_revision!r}"
        )
    return {
        "head_revision": head_revision,
        "current_revision": current_revision,
        "version_num": version_num,
    }


def wait_for_url(
    url: str, *, timeout_seconds: int, process: subprocess.Popen[str]
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"temporary app server exited early with code {process.returncode}"
            )
        try:
            response = requests.get(url, timeout=2)
        except requests.RequestException:
            time.sleep(1)
            continue
        if response.ok:
            return
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {url}")


def run_app_smoke(env: dict[str, str], *, timeout_seconds: int) -> dict[str, Any]:
    base_url = f"http://127.0.0.1:{env['APP_PORT']}"
    server_env = env.copy()
    server_env["APP_SERVER"] = "gunicorn"
    server_env["PGPORT"] = server_env["BASE_PGPORT"]
    server_env["APP_PORT"] = server_env["BASE_APP_PORT"]
    process = subprocess.Popen(
        ["bash", str(PROJECT_ROOT / "scripts" / "serve.sh")],
        cwd=PROJECT_ROOT,
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_url(
            f"{base_url}/health/db", timeout_seconds=timeout_seconds, process=process
        )
        login_response = requests.get(f"{base_url}/auth/login", timeout=5)
        health_response = requests.get(f"{base_url}/health/db", timeout=5)
        if not login_response.ok:
            raise RuntimeError(
                f"/auth/login smoke failed with {login_response.status_code}"
            )
        if not health_response.ok:
            raise RuntimeError(
                f"/health/db smoke failed with {health_response.status_code}"
            )
        return {
            "base_url": base_url,
            "auth_login_status": login_response.status_code,
            "health_status": health_response.status_code,
            "health_payload": health_response.json(),
        }
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    args = parse_args()
    env = resolve_runtime_env(args)

    summary: dict[str, Any] = {
        "database": env["PGDATABASE"],
        "source_database": env["REHEARSAL_SOURCE_DATABASE"],
        "pg_host": env["PGHOST"],
        "pg_port": int(env["PGPORT"]),
        "app_port": int(env["APP_PORT"]),
        "seed_file": resolve_repo_path(args.seed_file),
    }

    bootstrap = bootstrap_database(args, env)
    summary["bootstrap"] = bootstrap

    alembic = stamp_and_verify_alembic(env)
    summary["alembic"] = alembic

    if not args.skip_app_smoke:
        summary["smoke"] = run_app_smoke(
            env, timeout_seconds=args.smoke_timeout_seconds
        )

    if args.json:
        json.dump(summary, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
