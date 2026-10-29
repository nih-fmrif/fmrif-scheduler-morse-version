#!/usr/bin/env python3
"""Verify current SQL bootstrap compatibility against old bootstrapped data.

This script bootstraps the old repository into a compatibility database,
generates rooted seed subsets in both supported researcher-code stages, and
then boots the current migration chain against each generated seed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OLD_REPO_ROOT = (
    Path.home() / ".codex" / "worktrees" / "ade3" / "fmrif-scheduler-morse-version"
)
SUPPORTED_STAGES = ("pre-018", "post-018")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--old-repo-root",
        default=str(DEFAULT_OLD_REPO_ROOT),
        help=(
            "Old repository root used to bootstrap the compatibility database "
            f"(default: {DEFAULT_OLD_REPO_ROOT})"
        ),
    )
    parser.add_argument(
        "--old-database",
        default=os.getenv("OLD_BOOTSTRAP_COMPAT_DATABASE", "fmrif_scheduler_oldcompat"),
        help="Database name used for the bootstrapped old repository",
    )
    parser.add_argument(
        "--current-db-prefix",
        default=os.getenv(
            "OLD_BOOTSTRAP_CURRENT_DB_PREFIX", "fmrif_scheduler_oldcompat_verify"
        ),
        help="Prefix for current-chain verification databases",
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=SUPPORTED_STAGES,
        default=[],
        help="Researcher-code stage to verify; repeatable. Defaults to both stages.",
    )
    parser.add_argument(
        "--template",
        action="append",
        default=[],
        metavar="DEVICE:TEMPLATE",
        help="Subset template to export; repeatable. Defaults to generator defaults.",
    )
    parser.add_argument(
        "--skip-old-bootstrap",
        action="store_true",
        help="Reuse the existing old compatibility database instead of recreating it.",
    )
    parser.add_argument(
        "--skip-additive-layer",
        action="store_true",
        help="Disable SQL_ADDITIVE_LAYER_FILES when verifying the current chain.",
    )
    return parser.parse_args()


def run(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def build_pg_env(prefix: str, fallback: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env["PGHOST"] = os.getenv(f"{prefix}_PGHOST", fallback.get("PGHOST", "127.0.0.1"))
    env["PGPORT"] = os.getenv(f"{prefix}_PGPORT", fallback.get("PGPORT", "5444"))
    env["PGUSER"] = os.getenv(f"{prefix}_PGUSER", fallback.get("PGUSER", "postgres"))
    env["PGPASSWORD"] = os.getenv(
        f"{prefix}_PGPASSWORD", fallback.get("PGPASSWORD", "password")
    )
    env["PGGSSENCMODE"] = os.getenv(
        f"{prefix}_PGGSSENCMODE", fallback.get("PGGSSENCMODE", "disable")
    )
    return env


def psql_query(env: dict[str, str], database: str, sql: str) -> str:
    proc = run(
        [
            "psql",
            "-X",
            "-A",
            "-t",
            "-F",
            "\t",
            "-d",
            database,
            "-c",
            sql,
        ],
        env=env,
        capture_output=True,
    )
    return proc.stdout.strip()


def bootstrap_old_database(
    args: argparse.Namespace, source_env: dict[str, str]
) -> None:
    run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "bootstrap-old-compat-db.sh"),
            args.old_repo_root,
            args.old_database,
        ],
        env=source_env,
        cwd=PROJECT_ROOT,
    )


def generate_seed(
    args: argparse.Namespace,
    source_env: dict[str, str],
    stage: str,
    output_path: Path,
) -> None:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "generate-rooted-template-seed.py"),
        "--database",
        args.old_database,
        "--researcher-stage",
        stage,
    ]
    for template in args.template:
        cmd.extend(["--template", template])

    with output_path.open("w", encoding="utf-8") as handle:
        subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=source_env,
            check=True,
            stdout=handle,
            text=True,
        )


def bootstrap_current_database(
    env: dict[str, str], database: str, seed_path: Path, skip_additive_layer: bool
) -> None:
    bootstrap_env = env.copy()
    bootstrap_env["PGDATABASE"] = database
    bootstrap_env["DROP_DB"] = "true"
    bootstrap_env["SQL_SEED_DUMP_FILE"] = str(seed_path)
    if skip_additive_layer:
        bootstrap_env["SQL_ADDITIVE_LAYER_FILES"] = ""

    run(
        ["bash", str(PROJECT_ROOT / "sql" / "000-init.sh")],
        env=bootstrap_env,
        cwd=PROJECT_ROOT,
    )


def collect_metrics(env: dict[str, str], database: str) -> dict[str, int]:
    row = psql_query(
        env,
        database,
        """
        select
            (select count(*) from tbltemplates) as templates,
            (select count(*) from tbltemplate) as template_cells,
            (
                select count(*)
                from (
                    select scannercode, templatecode
                    from tbltemplate
                    group by scannercode, templatecode
                    having count(*) <> 168
                ) malformed
            ) as malformed_templates,
            (select count(*) from tlkpresearcher where researchercode like '%[OLD]') as old_researchers,
            (select count(*) from tbltemplate where researchercode like '%[OLD]') as old_template_cells,
            (select count(*) from tbltemplate where deptcode = '(none)') as none_template_cells
        """,
    )
    values = row.split("\t")
    return {
        "templates": int(values[0]),
        "template_cells": int(values[1]),
        "malformed_templates": int(values[2]),
        "old_researchers": int(values[3]),
        "old_template_cells": int(values[4]),
        "none_template_cells": int(values[5]),
    }


def validate_metrics(stage: str, metrics: dict[str, int]) -> None:
    if metrics["templates"] <= 0:
        raise SystemExit(f"{stage}: no templates were loaded")
    if metrics["template_cells"] <= 0:
        raise SystemExit(f"{stage}: no template cells were loaded")
    if metrics["malformed_templates"] != 0:
        raise SystemExit(f"{stage}: found malformed template slot counts: {metrics}")
    if metrics["old_researchers"] <= 0:
        raise SystemExit(
            f"{stage}: expected rooted [OLD] researcher rows after bootstrap"
        )
    if metrics["old_template_cells"] <= 0:
        raise SystemExit(
            f"{stage}: expected rooted [OLD] template references after bootstrap"
        )
    if metrics["none_template_cells"] <= 0:
        raise SystemExit(
            f"{stage}: expected rooted '(none)' template cells after bootstrap"
        )


def main() -> None:
    args = parse_args()
    stages = args.stage or list(SUPPORTED_STAGES)

    default_env = os.environ.copy()
    default_env.setdefault("PGHOST", "127.0.0.1")
    default_env.setdefault("PGPORT", "5444")
    default_env.setdefault("PGUSER", "postgres")
    default_env.setdefault("PGPASSWORD", "password")
    default_env.setdefault("PGGSSENCMODE", "disable")

    source_env = build_pg_env("OLD_BOOTSTRAP", default_env)
    target_env = build_pg_env("TARGET", default_env)

    if not args.skip_old_bootstrap:
        bootstrap_old_database(args, source_env)

    results: dict[str, dict[str, int]] = {}
    with tempfile.TemporaryDirectory(prefix="old-bootstrap-compat-") as temp_dir:
        temp_root = Path(temp_dir)
        for stage in stages:
            seed_path = temp_root / f"seed-{stage}.sql"
            generate_seed(args, source_env, stage, seed_path)
            current_db = f"{args.current_db_prefix}_{stage.replace('-', '_')}"
            bootstrap_current_database(
                target_env, current_db, seed_path, args.skip_additive_layer
            )
            metrics = collect_metrics(target_env, current_db)
            validate_metrics(stage, metrics)
            results[stage] = metrics

    json.dump(results, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
