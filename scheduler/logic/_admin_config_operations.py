"""Admin-managed operational settings and status helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy.exc import SQLAlchemyError

from scheduler import model
from scheduler.config import settings
from scheduler.db_runtime import probe_database_health

from ._admin_config_settings import (
    admin_settings_available,
    get_admin_setting,
    set_admin_setting,
)

ADMIN_SETTING_KEY_BACKUP_ENABLED = "ops.backup.enabled"
ADMIN_SETTING_KEY_BACKUP_DIRECTORY = "ops.backup.directory"
ADMIN_SETTING_KEY_BACKUP_FORMAT = "ops.backup.format"
ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT = "ops.backup.retention_count"
ADMIN_SETTING_KEY_BACKUP_MAX_AGE_HOURS = "ops.backup.max_age_hours"
ADMIN_SETTING_KEY_BACKUP_MIN_FREE_GB = "ops.backup.min_free_gb"
ADMIN_SETTING_KEY_BACKUP_LAST_ATTEMPT_AT = "ops.backup.last_attempt_at"
ADMIN_SETTING_KEY_BACKUP_LAST_SUCCESS_AT = "ops.backup.last_success_at"
ADMIN_SETTING_KEY_BACKUP_LAST_STATUS = "ops.backup.last_status"
ADMIN_SETTING_KEY_BACKUP_LAST_MESSAGE = "ops.backup.last_message"
ADMIN_SETTING_KEY_BACKUP_LAST_PATH = "ops.backup.last_path"
ADMIN_SETTING_KEY_BACKUP_LAST_SIZE_BYTES = "ops.backup.last_size_bytes"
ADMIN_SETTING_KEY_RESTORE_ENABLED = "ops.restore.enabled"
ADMIN_SETTING_KEY_RESTORE_INTERVAL_DAYS = "ops.restore.interval_days"
ADMIN_SETTING_KEY_RESTORE_LAST_ATTEMPT_AT = "ops.restore.last_attempt_at"
ADMIN_SETTING_KEY_RESTORE_LAST_SUCCESS_AT = "ops.restore.last_success_at"
ADMIN_SETTING_KEY_RESTORE_LAST_STATUS = "ops.restore.last_status"
ADMIN_SETTING_KEY_RESTORE_LAST_MESSAGE = "ops.restore.last_message"
ADMIN_SETTING_KEY_RESTORE_LAST_DATABASE = "ops.restore.last_database"
ADMIN_SETTING_KEY_RESTORE_LAST_DURATION_SECONDS = "ops.restore.last_duration_seconds"

DEFAULT_BACKUP_DIRECTORY = "/var/lib/fmrif-scheduler/backups"
BACKUP_FORMAT_CUSTOM = "custom"
BACKUP_FORMAT_PLAIN = "plain"
DEFAULT_BACKUP_FORMAT = BACKUP_FORMAT_CUSTOM
DEFAULT_BACKUP_RETENTION_COUNT = 7
DEFAULT_BACKUP_MAX_AGE_HOURS = 36
DEFAULT_BACKUP_MIN_FREE_GB = 5
DEFAULT_BACKUP_ENABLED = True
DEFAULT_RESTORE_ENABLED = True
DEFAULT_RESTORE_INTERVAL_DAYS = 7
GLOBALS_BACKUP_FORMAT = "globals"
GLOBALS_BACKUP_SUFFIX = ".globals.sql"


@dataclass(frozen=True)
class BackupOperationsConfig:
    enabled: bool = DEFAULT_BACKUP_ENABLED
    directory: str = DEFAULT_BACKUP_DIRECTORY
    format: str = DEFAULT_BACKUP_FORMAT
    retention_count: int = DEFAULT_BACKUP_RETENTION_COUNT
    max_age_hours: int = DEFAULT_BACKUP_MAX_AGE_HOURS
    min_free_gb: int = DEFAULT_BACKUP_MIN_FREE_GB


@dataclass(frozen=True)
class RestoreDrillOperationsConfig:
    enabled: bool = DEFAULT_RESTORE_ENABLED
    interval_days: int = DEFAULT_RESTORE_INTERVAL_DAYS


@dataclass(frozen=True)
class AdminOperationResult:
    status: str
    detail: str
    backup_path: str = ""
    backup_format: str = ""
    size_bytes: int | None = None
    pruned_paths: tuple[str, ...] = ()
    database_name: str = ""
    duration_seconds: float | None = None
    next_due_at: str = ""
    exit_code: int | None = None
    command: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "detail": self.detail,
        }
        if self.backup_path:
            payload["backup_path"] = self.backup_path
        if self.backup_format:
            payload["backup_format"] = self.backup_format
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.pruned_paths:
            payload["pruned_paths"] = list(self.pruned_paths)
        if self.database_name:
            payload["database_name"] = self.database_name
        if self.duration_seconds is not None:
            payload["duration_seconds"] = round(float(self.duration_seconds), 3)
        if self.next_due_at:
            payload["next_due_at"] = self.next_due_at
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.command:
            payload["command"] = list(self.command)
        return payload


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = _normalize_text(value).lower()
    if normalized == "":
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _normalize_positive_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    field_name: str,
) -> int:
    normalized = _normalize_text(value)
    if normalized == "":
        return default
    try:
        parsed = int(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a whole number") from exc
    if parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return parsed


def _normalize_backup_format(value: Any, *, default: str) -> str:
    normalized = _normalize_text(value).lower()
    if normalized == "":
        return default
    if normalized in {BACKUP_FORMAT_CUSTOM, BACKUP_FORMAT_PLAIN}:
        return normalized
    raise ValueError("backup format must be custom or plain")


def _parse_timestamp(value: str) -> datetime | None:
    normalized = _normalize_text(value)
    if normalized == "":
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _format_bytes(value: int | None) -> str:
    if value is None or value < 0:
        return ""
    return str(int(value))


def _parse_int(value: str, *, default: int | None = None) -> int | None:
    normalized = _normalize_text(value)
    if normalized == "":
        return default
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return default


def _backup_directory_path(directory: str) -> Path:
    return Path(directory).expanduser()


def _backup_extension_for_format(backup_format: str) -> str:
    if backup_format == BACKUP_FORMAT_PLAIN:
        return ".sql"
    return ".dump"


def _backup_format_for_path(path: Path | str | None) -> str:
    if path is None:
        return ""
    suffix = Path(path).suffix.lower()
    if suffix == ".sql":
        return BACKUP_FORMAT_PLAIN
    if suffix in {".dump", ".backup"}:
        return BACKUP_FORMAT_CUSTOM
    return ""


def _is_globals_backup_file(path: Path) -> bool:
    return path.name.endswith(GLOBALS_BACKUP_SUFFIX)


def _normalize_temp_db_name(base_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", base_name).strip("_").lower()
    normalized = normalized or "scheduler"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = f"_restore_{timestamp}"
    max_prefix = max(1, 63 - len(suffix))
    return f"{normalized[:max_prefix]}{suffix}"


def _pg_command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.PGPASSWORD
    return env


def _command_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )


def _admin_connection():
    conn = psycopg2.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
        database="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    conn.autocommit = True
    return conn


def _drop_database(
    conn,
    database_name: str,
    *,
    retry_timeout_seconds: float = 5.0,
    retry_interval_seconds: float = 0.5,
) -> None:
    database_sql = sql.Identifier(database_name)
    deadline = time.monotonic() + retry_timeout_seconds

    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            if cur.fetchone() is None:
                return

            cur.execute(
                sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(
                    database_sql
                )
            )
            cur.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    database_sql
                )
            )
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                  AND usename = current_user
                """,
                (database_name,),
            )
            try:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(database_sql))
                return
            except psycopg2.Error:
                if time.monotonic() >= deadline:
                    raise
        time.sleep(retry_interval_seconds)


def _reset_admin_settings_session() -> None:
    try:
        model.db.session.rollback()
    except SQLAlchemyError:
        pass
    model.db.session.remove()


def get_admin_backup_operations_config() -> BackupOperationsConfig:
    return BackupOperationsConfig(
        enabled=_normalize_bool(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_ENABLED,
                "true" if DEFAULT_BACKUP_ENABLED else "false",
            ),
            default=DEFAULT_BACKUP_ENABLED,
        ),
        directory=_normalize_text(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                DEFAULT_BACKUP_DIRECTORY,
            )
        )
        or DEFAULT_BACKUP_DIRECTORY,
        format=_normalize_backup_format(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_FORMAT,
                DEFAULT_BACKUP_FORMAT,
            ),
            default=DEFAULT_BACKUP_FORMAT,
        ),
        retention_count=_normalize_positive_int(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT,
                str(DEFAULT_BACKUP_RETENTION_COUNT),
            ),
            default=DEFAULT_BACKUP_RETENTION_COUNT,
            minimum=1,
            field_name="backup retention count",
        ),
        max_age_hours=_normalize_positive_int(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_MAX_AGE_HOURS,
                str(DEFAULT_BACKUP_MAX_AGE_HOURS),
            ),
            default=DEFAULT_BACKUP_MAX_AGE_HOURS,
            minimum=1,
            field_name="backup max age (hours)",
        ),
        min_free_gb=_normalize_positive_int(
            get_admin_setting(
                ADMIN_SETTING_KEY_BACKUP_MIN_FREE_GB,
                str(DEFAULT_BACKUP_MIN_FREE_GB),
            ),
            default=DEFAULT_BACKUP_MIN_FREE_GB,
            minimum=1,
            field_name="backup minimum free disk (GB)",
        ),
    )


def get_admin_restore_drill_operations_config() -> RestoreDrillOperationsConfig:
    return RestoreDrillOperationsConfig(
        enabled=_normalize_bool(
            get_admin_setting(
                ADMIN_SETTING_KEY_RESTORE_ENABLED,
                "true" if DEFAULT_RESTORE_ENABLED else "false",
            ),
            default=DEFAULT_RESTORE_ENABLED,
        ),
        interval_days=_normalize_positive_int(
            get_admin_setting(
                ADMIN_SETTING_KEY_RESTORE_INTERVAL_DAYS,
                str(DEFAULT_RESTORE_INTERVAL_DAYS),
            ),
            default=DEFAULT_RESTORE_INTERVAL_DAYS,
            minimum=1,
            field_name="restore drill interval (days)",
        ),
    )


def parse_admin_operations_form(
    values: Mapping[str, Any],
) -> tuple[BackupOperationsConfig, RestoreDrillOperationsConfig]:
    backup_config = BackupOperationsConfig(
        enabled=_normalize_bool(values.get("ops_backup_enabled"), default=False),
        directory=_normalize_text(values.get("ops_backup_directory"))
        or DEFAULT_BACKUP_DIRECTORY,
        format=_normalize_backup_format(
            values.get("ops_backup_format"),
            default=DEFAULT_BACKUP_FORMAT,
        ),
        retention_count=_normalize_positive_int(
            values.get("ops_backup_retention_count"),
            default=DEFAULT_BACKUP_RETENTION_COUNT,
            minimum=1,
            field_name="backup retention count",
        ),
        max_age_hours=_normalize_positive_int(
            values.get("ops_backup_max_age_hours"),
            default=DEFAULT_BACKUP_MAX_AGE_HOURS,
            minimum=1,
            field_name="backup max age (hours)",
        ),
        min_free_gb=_normalize_positive_int(
            values.get("ops_backup_min_free_gb"),
            default=DEFAULT_BACKUP_MIN_FREE_GB,
            minimum=1,
            field_name="backup minimum free disk (GB)",
        ),
    )
    restore_config = RestoreDrillOperationsConfig(
        enabled=_normalize_bool(values.get("ops_restore_enabled"), default=False),
        interval_days=_normalize_positive_int(
            values.get("ops_restore_interval_days"),
            default=DEFAULT_RESTORE_INTERVAL_DAYS,
            minimum=1,
            field_name="restore drill interval (days)",
        ),
    )
    return backup_config, restore_config


def set_admin_operations_config(
    backup_config: BackupOperationsConfig,
    restore_config: RestoreDrillOperationsConfig,
    *,
    updated_by: Optional[str] = None,
) -> bool:
    configured = False
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_ENABLED,
        "true" if backup_config.enabled else "false",
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
        backup_config.directory,
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_FORMAT,
        backup_config.format,
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT,
        str(backup_config.retention_count),
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_MAX_AGE_HOURS,
        str(backup_config.max_age_hours),
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_MIN_FREE_GB,
        str(backup_config.min_free_gb),
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_RESTORE_ENABLED,
        "true" if restore_config.enabled else "false",
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_RESTORE_INTERVAL_DAYS,
        str(restore_config.interval_days),
        updated_by=updated_by,
    )
    return configured


def backup_directory_path(config: BackupOperationsConfig | None = None) -> Path:
    return _backup_directory_path(
        (config or get_admin_backup_operations_config()).directory
    )


def list_backup_files(config: BackupOperationsConfig | None = None) -> list[Path]:
    directory = backup_directory_path(config)
    if not directory.is_dir():
        return []
    return sorted(
        [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix in {".dump", ".sql", ".backup"}
            and not _is_globals_backup_file(path)
        ],
        key=lambda path: path.name,
        reverse=True,
    )


def latest_backup_file(config: BackupOperationsConfig | None = None) -> Path | None:
    files = list_backup_files(config)
    return files[0] if files else None


def list_globals_backup_files(
    config: BackupOperationsConfig | None = None,
) -> list[Path]:
    directory = backup_directory_path(config)
    if not directory.is_dir():
        return []
    return sorted(
        [
            path
            for path in directory.iterdir()
            if path.is_file() and _is_globals_backup_file(path)
        ],
        key=lambda path: path.name,
        reverse=True,
    )


def latest_globals_backup_file(
    config: BackupOperationsConfig | None = None,
) -> Path | None:
    files = list_globals_backup_files(config)
    return files[0] if files else None


def prune_backup_files(config: BackupOperationsConfig | None = None) -> list[Path]:
    backup_config = config or get_admin_backup_operations_config()
    files = list_backup_files(backup_config)
    removed: list[Path] = []
    for obsolete_path in files[backup_config.retention_count :]:
        obsolete_path.unlink(missing_ok=True)
        removed.append(obsolete_path)
    return removed


def prune_globals_backup_files(
    config: BackupOperationsConfig | None = None,
) -> list[Path]:
    backup_config = config or get_admin_backup_operations_config()
    files = list_globals_backup_files(backup_config)
    removed: list[Path] = []
    for obsolete_path in files[backup_config.retention_count :]:
        obsolete_path.unlink(missing_ok=True)
        removed.append(obsolete_path)
    return removed


def record_backup_execution(
    *,
    success: bool,
    updated_by: Optional[str] = None,
    attempted_at: datetime | None = None,
    backup_path: str = "",
    size_bytes: int | None = None,
    message: str = "",
) -> bool:
    timestamp = attempted_at or datetime.now(timezone.utc)
    configured = False
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_LAST_ATTEMPT_AT,
        _format_timestamp(timestamp),
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_LAST_STATUS,
        "success" if success else "error",
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_BACKUP_LAST_MESSAGE,
        _normalize_text(message),
        updated_by=updated_by,
    )
    if backup_path:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_BACKUP_LAST_PATH,
            backup_path,
            updated_by=updated_by,
        )
    if size_bytes is not None:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_BACKUP_LAST_SIZE_BYTES,
            _format_bytes(size_bytes),
            updated_by=updated_by,
        )
    if success:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_BACKUP_LAST_SUCCESS_AT,
            _format_timestamp(timestamp),
            updated_by=updated_by,
        )
    return configured


def record_restore_drill_execution(
    *,
    success: bool,
    updated_by: Optional[str] = None,
    attempted_at: datetime | None = None,
    database_name: str = "",
    duration_seconds: float | None = None,
    message: str = "",
) -> bool:
    timestamp = attempted_at or datetime.now(timezone.utc)
    configured = False
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_RESTORE_LAST_ATTEMPT_AT,
        _format_timestamp(timestamp),
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_RESTORE_LAST_STATUS,
        "success" if success else "error",
        updated_by=updated_by,
    )
    configured |= set_admin_setting(
        ADMIN_SETTING_KEY_RESTORE_LAST_MESSAGE,
        _normalize_text(message),
        updated_by=updated_by,
    )
    if database_name:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_RESTORE_LAST_DATABASE,
            database_name,
            updated_by=updated_by,
        )
    if duration_seconds is not None:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_RESTORE_LAST_DURATION_SECONDS,
            json.dumps(round(float(duration_seconds), 3)),
            updated_by=updated_by,
        )
    if success:
        configured |= set_admin_setting(
            ADMIN_SETTING_KEY_RESTORE_LAST_SUCCESS_AT,
            _format_timestamp(timestamp),
            updated_by=updated_by,
        )
    return configured


def run_backup_operation(
    *,
    force: bool = False,
    updated_by: Optional[str] = None,
    backup_format: str | None = None,
) -> AdminOperationResult:
    attempted_at = datetime.now(timezone.utc)
    backup_config = get_admin_backup_operations_config()
    selected_format = _normalize_backup_format(
        backup_format,
        default=backup_config.format,
    )
    if not backup_config.enabled and not force:
        return AdminOperationResult(
            status="skipped",
            detail="backups are disabled",
        )

    backup_dir = backup_directory_path(backup_config)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = attempted_at.strftime("%Y%m%dT%H%M%SZ")
    output_path = backup_dir / (
        f"{settings.PGDATABASE}-{timestamp}"
        f"{_backup_extension_for_format(selected_format)}"
    )
    command = (
        "pg_dump",
        f"--format={selected_format}",
        "--no-owner",
        "--no-privileges",
        "-h",
        settings.PGHOST,
        "-p",
        str(settings.PGPORT),
        "-U",
        settings.PGUSER,
        "-d",
        settings.PGDATABASE,
        "-f",
        str(output_path),
    )

    _reset_admin_settings_session()
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            text=True,
            capture_output=True,
            env=_pg_command_env(),
        )
    except Exception as exc:
        message = _normalize_text(exc) or "pg_dump failed"
        _reset_admin_settings_session()
        record_backup_execution(
            success=False,
            updated_by=updated_by,
            attempted_at=attempted_at,
            message=message,
        )
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_format=selected_format,
            exit_code=1,
            command=command,
        )

    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        message = _command_output(completed) or "pg_dump failed"
        _reset_admin_settings_session()
        record_backup_execution(
            success=False,
            updated_by=updated_by,
            attempted_at=attempted_at,
            message=message,
        )
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_format=selected_format,
            exit_code=completed.returncode or 1,
            command=command,
        )

    size_bytes = int(output_path.stat().st_size)
    removed = tuple(str(path) for path in prune_backup_files(backup_config))
    message = f"created {output_path.name} ({selected_format} format)"
    if removed:
        message += f"; pruned {len(removed)} older backups"
    _reset_admin_settings_session()
    record_backup_execution(
        success=True,
        updated_by=updated_by,
        attempted_at=attempted_at,
        backup_path=str(output_path),
        size_bytes=size_bytes,
        message=message,
    )
    return AdminOperationResult(
        status="ok",
        detail=message,
        backup_path=str(output_path),
        backup_format=selected_format,
        size_bytes=size_bytes,
        pruned_paths=removed,
        command=command,
    )


def run_restore_drill_operation(
    *,
    force: bool = False,
    updated_by: Optional[str] = None,
) -> AdminOperationResult:
    attempted_at = datetime.now(timezone.utc)
    restore_config = get_admin_restore_drill_operations_config()
    restore_status = collect_restore_drill_status(restore_config)
    latest_backup = latest_backup_file()

    if latest_backup is None:
        message = "no backup file is available for a restore drill"
        record_restore_drill_execution(
            success=False,
            updated_by=updated_by,
            attempted_at=attempted_at,
            message=message,
        )
        return AdminOperationResult(status="error", detail=message, exit_code=1)

    if not restore_config.enabled and not force:
        return AdminOperationResult(
            status="skipped",
            detail="restore drills are disabled",
        )

    if restore_config.enabled and not restore_status["due_now"] and not force:
        return AdminOperationResult(
            status="skipped",
            detail="restore drill is not due yet",
            next_due_at=_normalize_text(restore_status.get("next_due_at")),
        )

    temp_db = _normalize_temp_db_name(settings.PGDATABASE)
    started_at = time.perf_counter()
    conn = None
    restore_command: tuple[str, ...] = ()
    _reset_admin_settings_session()
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(temp_db)))

        if latest_backup.suffix == ".sql":
            restore_command = (
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                settings.PGHOST,
                "-p",
                str(settings.PGPORT),
                "-U",
                settings.PGUSER,
                "-d",
                temp_db,
                "-f",
                str(latest_backup),
            )
        else:
            restore_command = (
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "-h",
                settings.PGHOST,
                "-p",
                str(settings.PGPORT),
                "-U",
                settings.PGUSER,
                "-d",
                temp_db,
                str(latest_backup),
            )

        completed = subprocess.run(
            list(restore_command),
            check=False,
            text=True,
            capture_output=True,
            env=_pg_command_env(),
        )
        if completed.returncode != 0:
            raise RuntimeError(_command_output(completed) or "restore command failed")

        verify_conn = psycopg2.connect(
            host=settings.PGHOST,
            port=settings.PGPORT,
            user=settings.PGUSER,
            password=settings.PGPASSWORD,
            database=temp_db,
        )
        try:
            with verify_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      to_regclass('public.tlkpresearcher') IS NOT NULL,
                      to_regclass('public.tlkpdept') IS NOT NULL,
                      to_regclass('public.tblsched') IS NOT NULL
                    """
                )
                users_ok, groups_ok, schedule_ok = cur.fetchone()
            if not (users_ok and groups_ok and schedule_ok):
                raise RuntimeError(
                    "restored database is missing one or more expected core tables"
                )
        finally:
            verify_conn.close()

        duration_seconds = time.perf_counter() - started_at
        message = f"restore drill succeeded from {latest_backup.name}"
        _reset_admin_settings_session()
        record_restore_drill_execution(
            success=True,
            updated_by=updated_by,
            attempted_at=attempted_at,
            database_name=temp_db,
            duration_seconds=duration_seconds,
            message=message,
        )
        return AdminOperationResult(
            status="ok",
            detail=message,
            backup_path=str(latest_backup),
            database_name=temp_db,
            duration_seconds=duration_seconds,
        )
    except Exception as exc:
        duration_seconds = time.perf_counter() - started_at
        message = _normalize_text(exc) or "restore drill failed"
        _reset_admin_settings_session()
        record_restore_drill_execution(
            success=False,
            updated_by=updated_by,
            attempted_at=attempted_at,
            database_name=temp_db,
            duration_seconds=duration_seconds,
            message=message,
        )
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_path=str(latest_backup),
            database_name=temp_db,
            duration_seconds=duration_seconds,
            exit_code=1,
            command=restore_command,
        )
    finally:
        if conn is not None:
            try:
                _drop_database(conn, temp_db)
            finally:
                conn.close()


def run_globals_backup_operation(
    *,
    force: bool = False,
    updated_by: Optional[str] = None,
    owner_user: str = "",
    owner_group: str = "",
) -> AdminOperationResult:
    attempted_at = datetime.now(timezone.utc)
    backup_config = get_admin_backup_operations_config()

    backup_dir = backup_directory_path(backup_config)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = attempted_at.strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        backup_dir / f"{settings.PGDATABASE}-{timestamp}{GLOBALS_BACKUP_SUFFIX}"
    )
    command = (
        "runuser",
        "-u",
        "postgres",
        "--",
        "pg_dumpall",
        "--globals-only",
        "--no-role-passwords",
        "-p",
        str(settings.PGPORT),
    )

    try:
        with output_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                list(command),
                check=False,
                text=True,
                stdout=handle,
                stderr=subprocess.PIPE,
            )
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        message = _normalize_text(exc) or "pg_dumpall failed"
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_format=GLOBALS_BACKUP_FORMAT,
            exit_code=1,
            command=command,
        )

    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        message = _command_output(completed) or "pg_dumpall failed"
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_format=GLOBALS_BACKUP_FORMAT,
            exit_code=completed.returncode or 1,
            command=command,
        )

    try:
        if owner_user or owner_group:
            shutil.chown(
                output_path,
                user=owner_user or None,
                group=owner_group or None,
            )
        output_path.chmod(0o640)
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        message = _normalize_text(exc) or "failed to update globals backup ownership"
        return AdminOperationResult(
            status="error",
            detail=message,
            backup_format=GLOBALS_BACKUP_FORMAT,
            exit_code=1,
            command=command,
        )

    size_bytes = int(output_path.stat().st_size)
    removed = tuple(str(path) for path in prune_globals_backup_files(backup_config))
    message = f"created {output_path.name} (globals companion backup)"
    if removed:
        message += f"; pruned {len(removed)} older globals backups"
    return AdminOperationResult(
        status="ok",
        detail=message,
        backup_path=str(output_path),
        backup_format=GLOBALS_BACKUP_FORMAT,
        size_bytes=size_bytes,
        pruned_paths=removed,
        command=command,
    )


def collect_backup_status(
    config: BackupOperationsConfig | None = None,
) -> dict[str, Any]:
    backup_config = config or get_admin_backup_operations_config()
    directory = backup_directory_path(backup_config)
    latest_file = latest_backup_file(backup_config)

    disk_target = directory if directory.exists() else directory.parent
    free_gb = None
    free_disk_state = "unknown"
    free_disk_detail = "disk usage unavailable"
    try:
        usage = shutil.disk_usage(disk_target)
        free_gb = round(usage.free / (1024**3), 2)
        if free_gb < backup_config.min_free_gb:
            free_disk_state = "error"
            free_disk_detail = (
                f"free disk {free_gb} GB is below configured floor "
                f"({backup_config.min_free_gb} GB)"
            )
        else:
            free_disk_state = "ok"
            free_disk_detail = (
                f"free disk {free_gb} GB meets configured floor "
                f"({backup_config.min_free_gb} GB)"
            )
    except OSError:
        pass

    latest_backup_modified_at = None
    latest_backup_age_hours = None
    latest_backup_format = ""
    backup_age_state = "unknown"
    backup_age_detail = "no backup file found"
    latest_backup_size_bytes = None
    if latest_file is not None:
        latest_backup_format = _backup_format_for_path(latest_file)
        stats = latest_file.stat()
        latest_backup_modified_at = datetime.fromtimestamp(
            stats.st_mtime, tz=timezone.utc
        )
        latest_backup_size_bytes = int(stats.st_size)
        latest_backup_age_hours = round(
            (datetime.now(timezone.utc) - latest_backup_modified_at).total_seconds()
            / 3600.0,
            2,
        )
        if latest_backup_age_hours > backup_config.max_age_hours:
            backup_age_state = "error"
            backup_age_detail = (
                f"latest backup age {latest_backup_age_hours} h exceeds configured "
                f"maximum ({backup_config.max_age_hours} h)"
            )
        else:
            backup_age_state = "ok"
            backup_age_detail = (
                f"latest backup age {latest_backup_age_hours} h is within the "
                f"configured maximum ({backup_config.max_age_hours} h)"
            )
    elif not backup_config.enabled:
        backup_age_state = "disabled"
        backup_age_detail = "backups are disabled"
    elif not directory.exists():
        backup_age_state = "error"
        backup_age_detail = "backup directory does not exist yet"

    return {
        "enabled": backup_config.enabled,
        "directory": str(directory),
        "directory_exists": directory.exists(),
        "format": backup_config.format,
        "retention_count": backup_config.retention_count,
        "max_age_hours": backup_config.max_age_hours,
        "min_free_gb": backup_config.min_free_gb,
        "latest_backup_path": str(latest_file) if latest_file is not None else "",
        "latest_backup_format": latest_backup_format,
        "latest_backup_modified_at": _format_timestamp(latest_backup_modified_at),
        "latest_backup_age_hours": latest_backup_age_hours,
        "latest_backup_size_bytes": latest_backup_size_bytes,
        "backup_age_state": backup_age_state,
        "backup_age_detail": backup_age_detail,
        "free_disk_state": free_disk_state,
        "free_disk_detail": free_disk_detail,
        "free_disk_gb": free_gb,
        "last_attempt_at": get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_ATTEMPT_AT),
        "last_success_at": get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_SUCCESS_AT),
        "last_status": get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_STATUS, "never"),
        "last_message": get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_MESSAGE),
        "last_path": get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_PATH),
        "last_size_bytes": _parse_int(
            get_admin_setting(ADMIN_SETTING_KEY_BACKUP_LAST_SIZE_BYTES),
            default=None,
        ),
    }


def collect_restore_drill_status(
    config: RestoreDrillOperationsConfig | None = None,
) -> dict[str, Any]:
    restore_config = config or get_admin_restore_drill_operations_config()
    last_success_at = _parse_timestamp(
        get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_SUCCESS_AT)
    )
    next_due_at = None
    due_now = False
    if restore_config.enabled:
        if last_success_at is None:
            due_now = True
        else:
            next_due_at = last_success_at + timedelta(days=restore_config.interval_days)
            due_now = datetime.now(timezone.utc) >= next_due_at

    duration_seconds = None
    duration_raw = get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_DURATION_SECONDS)
    if duration_raw:
        try:
            duration_seconds = float(json.loads(duration_raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            duration_seconds = None

    return {
        "enabled": restore_config.enabled,
        "interval_days": restore_config.interval_days,
        "last_attempt_at": get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_ATTEMPT_AT),
        "last_success_at": get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_SUCCESS_AT),
        "last_status": get_admin_setting(
            ADMIN_SETTING_KEY_RESTORE_LAST_STATUS, "never"
        ),
        "last_message": get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_MESSAGE),
        "last_database": get_admin_setting(ADMIN_SETTING_KEY_RESTORE_LAST_DATABASE),
        "last_duration_seconds": duration_seconds,
        "next_due_at": _format_timestamp(next_due_at),
        "due_now": due_now,
    }


def collect_admin_operations_status() -> dict[str, Any]:
    return {
        "database": probe_database_health(),
        "backup": collect_backup_status(),
        "restore_drill": collect_restore_drill_status(),
        "settings_available": admin_settings_available(),
    }


__all__ = [
    "ADMIN_SETTING_KEY_BACKUP_DIRECTORY",
    "ADMIN_SETTING_KEY_BACKUP_ENABLED",
    "ADMIN_SETTING_KEY_BACKUP_FORMAT",
    "ADMIN_SETTING_KEY_BACKUP_MAX_AGE_HOURS",
    "ADMIN_SETTING_KEY_BACKUP_MIN_FREE_GB",
    "ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT",
    "ADMIN_SETTING_KEY_RESTORE_ENABLED",
    "ADMIN_SETTING_KEY_RESTORE_INTERVAL_DAYS",
    "AdminOperationResult",
    "BACKUP_FORMAT_CUSTOM",
    "BACKUP_FORMAT_PLAIN",
    "BackupOperationsConfig",
    "DEFAULT_BACKUP_DIRECTORY",
    "DEFAULT_BACKUP_ENABLED",
    "DEFAULT_BACKUP_FORMAT",
    "DEFAULT_BACKUP_MAX_AGE_HOURS",
    "DEFAULT_BACKUP_MIN_FREE_GB",
    "DEFAULT_BACKUP_RETENTION_COUNT",
    "DEFAULT_RESTORE_ENABLED",
    "DEFAULT_RESTORE_INTERVAL_DAYS",
    "RestoreDrillOperationsConfig",
    "backup_directory_path",
    "collect_admin_operations_status",
    "collect_backup_status",
    "collect_restore_drill_status",
    "get_admin_backup_operations_config",
    "get_admin_restore_drill_operations_config",
    "latest_backup_file",
    "latest_globals_backup_file",
    "list_backup_files",
    "list_globals_backup_files",
    "parse_admin_operations_form",
    "prune_backup_files",
    "prune_globals_backup_files",
    "record_backup_execution",
    "record_restore_drill_execution",
    "run_backup_operation",
    "run_globals_backup_operation",
    "run_restore_drill_operation",
    "set_admin_operations_config",
]
