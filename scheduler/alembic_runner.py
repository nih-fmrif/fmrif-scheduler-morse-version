from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_option(value: str) -> str:
    return value.replace("%(here)s", str(PROJECT_ROOT))


def build_alembic_config() -> Config:
    pyproject = PROJECT_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    alembic_settings = data.get("tool", {}).get("alembic", {})
    if not isinstance(alembic_settings, dict):
        raise RuntimeError(f"Missing [tool.alembic] in {pyproject}.")

    config = Config()
    script_location = alembic_settings.get("script_location")
    if not isinstance(script_location, str) or not script_location.strip():
        raise RuntimeError(f"Missing tool.alembic.script_location in {pyproject}.")
    config.set_main_option("script_location", _resolve_option(script_location))

    version_locations = alembic_settings.get("version_locations")
    if isinstance(version_locations, list) and version_locations:
        config.set_main_option(
            "version_locations",
            " ".join(_resolve_option(str(location)) for location in version_locations),
        )

    return config


def _current_revision() -> str | None:
    from scheduler.config import settings

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Alembic commands using pyproject.toml-backed config."
    )
    parser.add_argument("command", choices=("upgrade", "stamp", "heads", "current"))
    parser.add_argument("revision", nargs="?")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = build_alembic_config()

    if args.command == "heads":
        script = ScriptDirectory.from_config(config)
        for revision in script.get_heads():
            print(revision)
        return 0

    if args.command == "current":
        revision = _current_revision()
        if revision:
            print(revision)
        return 0

    if args.revision is None:
        raise SystemExit(f"{args.command} requires a revision argument")

    if args.command == "upgrade":
        command.upgrade(config, args.revision)
        return 0

    command.stamp(config, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
