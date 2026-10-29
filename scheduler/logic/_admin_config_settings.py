"""Admin setting storage and mailing-list helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from scheduler import config, model

ADMIN_SETTING_KEY_LISTSERV = "core.listserv"
ADMIN_SETTING_KEY_DEFAULT_SENDER = "mail.default_sender"
ADMIN_SETTING_KEY_MAILING_LISTS = "mail.mailing_lists"
ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING = "core.group_institute_mapping"
ADMIN_SETTINGS_TABLE_NAME = "app_settings"
GROUP_INSTITUTE_HISTORY_WINDOW_YEARS = 2
GROUP_INSTITUTE_HISTORY_WINDOW_MAX_YEARS = 30


def admin_settings_available() -> bool:
    """Return whether the app settings table exists."""
    try:
        return inspect(model.db.engine).has_table(ADMIN_SETTINGS_TABLE_NAME)
    except Exception:
        return False


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_group_institute_history_window_years(
    value: Any,
    *,
    default: int = GROUP_INSTITUTE_HISTORY_WINDOW_YEARS,
) -> int:
    token = _normalize_text(value)
    if token == "":
        return default
    try:
        parsed = int(token)
    except (TypeError, ValueError):
        return default
    return max(1, min(GROUP_INSTITUTE_HISTORY_WINDOW_MAX_YEARS, parsed))


def get_admin_setting(key: str, default: str = "") -> str:
    if not admin_settings_available():
        return default
    try:
        row = model.db.session.get(model.AppSetting, key)
    except SQLAlchemyError:
        return default
    if row is None or row.value is None:
        return default
    return str(row.value)


def set_admin_setting(
    key: str,
    value: str,
    *,
    updated_by: Optional[str] = None,
) -> bool:
    if not admin_settings_available():
        return False
    row = model.db.session.get(model.AppSetting, key)
    if row is None:
        row = model.AppSetting(key=key)
    row.value = _normalize_text(value)
    row.updated_by = _normalize_text(updated_by) or None
    model.db.session.add(row)
    return True


def _coerce_mailings(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return dict(config.settings.mail.mailing_lists)
    out: Dict[str, str] = {}
    for name, desc in raw.items():
        if not isinstance(name, str):
            continue
        normalized_name = name.strip()
        if normalized_name == "":
            continue
        out[normalized_name] = "" if desc is None else str(desc)
    return out


def get_admin_listserv() -> str:
    return _normalize_text(
        get_admin_setting(ADMIN_SETTING_KEY_LISTSERV, config.settings.core.listserv)
    )


def get_admin_default_sender() -> str:
    return _normalize_text(
        get_admin_setting(
            ADMIN_SETTING_KEY_DEFAULT_SENDER,
            str(config.settings.mail.default_sender)
            if config.settings.mail.default_sender is not None
            else "",
        )
    )


def get_admin_mailing_lists() -> Dict[str, str]:
    raw = get_admin_setting(
        ADMIN_SETTING_KEY_MAILING_LISTS,
        json.dumps(config.settings.mail.mailing_lists, sort_keys=True),
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = config.settings.mail.mailing_lists
    return _coerce_mailings(parsed)


def format_admin_mailing_lists_for_form() -> str:
    return json.dumps(get_admin_mailing_lists(), sort_keys=True, indent=2)


def parse_admin_mailing_lists(raw_text: str) -> Dict[str, str]:
    payload = _normalize_text(raw_text)
    if payload == "":
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as ex:
        raise ValueError(f"mailing lists must be valid JSON: {ex}") from ex
    if not isinstance(parsed, dict):
        raise ValueError("mailing lists must be a JSON object")
    normalized = _coerce_mailings(parsed)
    if not normalized and parsed:
        raise ValueError("mailing lists must contain at least one non-empty key")
    return normalized


def set_admin_listserv(value: str, *, updated_by: Optional[str] = None) -> bool:
    return set_admin_setting(
        ADMIN_SETTING_KEY_LISTSERV,
        _normalize_text(value),
        updated_by=updated_by,
    )


def set_admin_default_sender(value: str, *, updated_by: Optional[str] = None) -> bool:
    return set_admin_setting(
        ADMIN_SETTING_KEY_DEFAULT_SENDER,
        _normalize_text(value),
        updated_by=updated_by,
    )


def set_admin_mailing_lists(
    values: Dict[str, str],
    *,
    updated_by: Optional[str] = None,
) -> bool:
    normalized = _coerce_mailings(values)
    return set_admin_setting(
        ADMIN_SETTING_KEY_MAILING_LISTS,
        json.dumps(normalized, sort_keys=True, indent=2),
        updated_by=updated_by,
    )


__all__ = [
    "ADMIN_SETTING_KEY_DEFAULT_SENDER",
    "ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING",
    "ADMIN_SETTING_KEY_LISTSERV",
    "ADMIN_SETTING_KEY_MAILING_LISTS",
    "GROUP_INSTITUTE_HISTORY_WINDOW_MAX_YEARS",
    "GROUP_INSTITUTE_HISTORY_WINDOW_YEARS",
    "admin_settings_available",
    "format_admin_mailing_lists_for_form",
    "get_admin_default_sender",
    "get_admin_listserv",
    "get_admin_mailing_lists",
    "get_admin_setting",
    "normalize_group_institute_history_window_years",
    "parse_admin_mailing_lists",
    "set_admin_default_sender",
    "set_admin_listserv",
    "set_admin_mailing_lists",
    "set_admin_setting",
]
