"""Typed payload shapes for admin operation status helpers."""

from __future__ import annotations

from typing import Any, TypedDict


class AdminOperationResultPayload(TypedDict, total=False):
    status: str
    detail: str
    backup_path: str
    backup_format: str
    size_bytes: int
    pruned_paths: list[str]
    database_name: str
    duration_seconds: float
    next_due_at: str
    exit_code: int
    command: list[str]


class BackupStatusPayload(TypedDict):
    enabled: bool
    directory: str
    directory_exists: bool
    format: str
    retention_count: int
    max_age_hours: int
    min_free_gb: int
    latest_backup_path: str
    latest_backup_format: str
    latest_backup_modified_at: str
    latest_backup_age_hours: float | None
    latest_backup_size_bytes: int | None
    backup_age_state: str
    backup_age_detail: str
    free_disk_state: str
    free_disk_detail: str
    free_disk_gb: float | None
    last_attempt_at: str
    last_success_at: str
    last_status: str
    last_message: str
    last_path: str
    last_size_bytes: int | None


class RestoreDrillStatusPayload(TypedDict):
    enabled: bool
    interval_days: int
    last_attempt_at: str
    last_success_at: str
    last_status: str
    last_message: str
    last_database: str
    last_duration_seconds: float | None
    next_due_at: str
    due_now: bool


class AdminOperationsStatusPayload(TypedDict):
    database: dict[str, Any]
    backup: BackupStatusPayload
    restore_drill: RestoreDrillStatusPayload
    settings_available: bool


__all__ = [
    "AdminOperationResultPayload",
    "AdminOperationsStatusPayload",
    "BackupStatusPayload",
    "RestoreDrillStatusPayload",
]
