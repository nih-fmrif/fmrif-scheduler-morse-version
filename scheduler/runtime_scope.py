from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

DEFAULT_RUNTIME_SCOPE_DIR = "/tmp/fmrif-scheduler-runtimes"
DEFAULT_DATABASE_ENV = {
    "PGHOST": "localhost",
    "PGPORT": "5444",
    "PGUSER": "postgres",
    "PGPASSWORD": "password",
    "PGDATABASE": "fmrif_scheduler",
}
DEFAULT_APP_PORT = "5051"


def _runtime_scope_dir() -> Path:
    return Path(os.environ.get("RUNTIME_SCOPE_DIR", DEFAULT_RUNTIME_SCOPE_DIR))


def sanitize_runtime_scope(raw_scope: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (raw_scope or "").strip().lower()).strip(
        "-"
    )
    return normalized or "default"


def runtime_scope_metadata_path(scope: str | None = None) -> Path:
    return _runtime_scope_dir() / sanitize_runtime_scope(
        scope or os.environ.get("FMRIF_RUNTIME_SCOPE")
    )


def load_runtime_scope_metadata(scope: str | None = None) -> dict[str, str]:
    path = runtime_scope_metadata_path(scope)
    if not path.is_file():
        return {}

    metadata: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def runtime_scope_offset(
    scope: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    metadata: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    resolved_scope = sanitize_runtime_scope(scope or env.get("FMRIF_RUNTIME_SCOPE"))
    scope_metadata = (
        load_runtime_scope_metadata(resolved_scope) if metadata is None else metadata
    )
    return int(
        env.get(
            "FMRIF_RUNTIME_SCOPE_OFFSET",
            scope_metadata.get("FMRIF_RUNTIME_SCOPE_OFFSET", "0"),
        )
        or "0"
    )


def resolve_scoped_runtime_values(
    names: Mapping[str, str],
    *,
    scope: str | None = None,
    environ: Mapping[str, str] | None = None,
    metadata: Mapping[str, str] | None = None,
    scoped_port_names: frozenset[str] | None = None,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    resolved_scope = sanitize_runtime_scope(scope or env.get("FMRIF_RUNTIME_SCOPE"))
    scope_metadata = (
        load_runtime_scope_metadata(resolved_scope) if metadata is None else metadata
    )
    offset = runtime_scope_offset(
        resolved_scope,
        environ=env,
        metadata=scope_metadata,
    )
    port_names = (
        frozenset({"PGPORT", "APP_PORT"})
        if scoped_port_names is None
        else scoped_port_names
    )

    resolved: dict[str, str] = {}
    for name, default in names.items():
        raw_value = env.get(name, scope_metadata.get(name, default))
        if name in port_names:
            base_port = int(raw_value)
            raw_value = str(
                base_port if resolved_scope == "default" else base_port + offset
            )
        resolved[name] = str(raw_value)
    resolved["FMRIF_RUNTIME_SCOPE_OFFSET"] = str(offset)
    return resolved


def apply_runtime_scope_database_env() -> dict[str, str]:
    scope = sanitize_runtime_scope(os.environ.get("FMRIF_RUNTIME_SCOPE"))
    metadata = load_runtime_scope_metadata(scope)
    if not metadata:
        return {}

    resolved = resolve_scoped_runtime_values(
        DEFAULT_DATABASE_ENV,
        scope=scope,
        environ=os.environ,
        metadata=metadata,
        scoped_port_names=frozenset({"PGPORT"}),
    )
    applied: dict[str, str] = {}

    def _set_default_env(name: str, value: str) -> None:
        if name in os.environ or not value:
            return
        os.environ[name] = value
        applied[name] = value

    _set_default_env("PGHOST", resolved["PGHOST"])
    _set_default_env("PGUSER", resolved["PGUSER"])
    _set_default_env("PGPASSWORD", resolved["PGPASSWORD"])
    _set_default_env("PGDATABASE", resolved["PGDATABASE"])
    _set_default_env("PGPORT", resolved["PGPORT"])
    if "FMRIF_RUNTIME_SCOPE_OFFSET" not in os.environ and metadata.get(
        "FMRIF_RUNTIME_SCOPE_OFFSET"
    ):
        os.environ["FMRIF_RUNTIME_SCOPE_OFFSET"] = resolved[
            "FMRIF_RUNTIME_SCOPE_OFFSET"
        ]
        applied["FMRIF_RUNTIME_SCOPE_OFFSET"] = os.environ["FMRIF_RUNTIME_SCOPE_OFFSET"]
    return applied


__all__ = [
    "apply_runtime_scope_database_env",
    "load_runtime_scope_metadata",
    "resolve_scoped_runtime_values",
    "runtime_scope_metadata_path",
    "runtime_scope_offset",
    "sanitize_runtime_scope",
]
