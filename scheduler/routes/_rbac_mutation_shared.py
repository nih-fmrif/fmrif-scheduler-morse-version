from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import scheduler.logic.rbac_audit_support as audit_logic
from scheduler import model

_RBAC_SCOPE_LABELS: Dict[str, str] = {
    "group": "groups",
    "device": "devices",
    "user": "users",
}
_RBAC_EMAIL_STATUS_OPTIONS: List[Dict[str, str]] = [
    {"value": audit_logic.EMAIL_STATUS_NONE, "label": audit_logic.EMAIL_STATUS_NONE},
    {"value": audit_logic.EMAIL_STATUS_SENT, "label": audit_logic.EMAIL_STATUS_SENT},
    {
        "value": audit_logic.EMAIL_STATUS_FAILED,
        "label": audit_logic.EMAIL_STATUS_FAILED,
    },
]


def _rbac_email_status(value: str) -> str:
    normalized = (value or "").strip().lower()
    options = [opt["value"] for opt in _RBAC_EMAIL_STATUS_OPTIONS]
    if normalized in options:
        return normalized
    return audit_logic.EMAIL_STATUS_NONE


def _rbac_permission_flags(ud: model.UserDevice) -> str:
    flags = []
    if bool(ud.templates):
        flags.append("templates")
    if bool(ud.slot):
        flags.append("edit any")
    if bool(ud.tech):
        flags.append("tech")
    if bool(ud.medical):
        flags.append("medical")
    if bool(ud.training):
        flags.append("training")
    if len(flags) == 0:
        return "none"
    return ", ".join(flags)


def _rbac_json_bool(raw: Any, *, field: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"invalid boolean value for {field}")


def _rbac_optional_json_bool(
    operation: Dict[str, Any],
    *,
    field: str,
) -> Optional[bool]:
    if field not in operation or operation.get(field) is None:
        return None
    return _rbac_json_bool(operation.get(field), field=field)


def _rbac_optional_json_string(
    operation: Dict[str, Any],
    *,
    field: str,
    max_length: Optional[int] = None,
) -> Optional[str]:
    if field not in operation or operation.get(field) is None:
        return None
    return _rbac_json_string(operation.get(field), field=field, max_length=max_length)


def _rbac_json_string(
    raw: Any,
    *,
    field: str,
    required: bool = False,
    max_length: Optional[int] = None,
) -> str:
    if raw is None:
        value = ""
    elif isinstance(raw, (str, int, float, bool)):
        value = str(raw)
    else:
        raise ValueError(f"invalid value for {field}")
    value = value.strip()
    if required and value == "":
        raise ValueError(f"{field} is required")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field} must be {max_length} characters or fewer")
    return value


def _rbac_json_email_status(raw: Any, *, field: str) -> str:
    token = _rbac_json_string(raw, field=field, required=True, max_length=10).lower()
    if token not in audit_logic.EMAIL_STATUS_VALUES:
        raise ValueError(
            f"{field} must be one of: {', '.join(audit_logic.EMAIL_STATUS_VALUES)}"
        )
    return token


def _rbac_optional_json_email_status(
    operation: Dict[str, Any], *, field: str
) -> Optional[str]:
    if field not in operation or operation.get(field) is None:
        return None
    return _rbac_json_email_status(operation.get(field), field=field)


def _rbac_validate_optional_url(value: str, *, field: str) -> None:
    if value == "":
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        raise ValueError(f"invalid URL for {field}")


def _rbac_audit_preview(value: Any) -> str:
    text_value = str(value if value is not None else "").strip()
    if text_value == "":
        return "none"
    compact = re.sub(r"\s+", " ", text_value).replace(",", ";")
    if len(compact) > 80:
        return f"{compact[:77]}..."
    return compact


class _RBACConflictError(ValueError):
    pass


def _rbac_parse_batch_operations(raw: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as ex:
        raise ValueError(f"invalid operations payload: {ex.msg}") from ex
    if not isinstance(parsed, list):
        raise ValueError("operations payload must be a list")
    if len(parsed) == 0:
        return []
    if len(parsed) > 1000:
        raise ValueError("operations payload may include at most 1000 changes")
    out: List[Dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("each operation must be an object")
        out.append(item)
    return out


def _rbac_validate_operation_scope(
    *,
    scope: str,
    entity: str,
    kind: str,
    group_id: str,
    device_id: str,
    user_id: str,
) -> None:
    if scope == "group":
        if group_id != entity:
            raise ValueError(f"{kind} must target selected group {entity}")
        return
    if scope == "device":
        if device_id != entity:
            raise ValueError(f"{kind} must target selected device {entity}")
        return
    if scope == "user":
        if user_id != entity:
            raise ValueError(f"{kind} must target selected user {entity}")
        return
    raise ValueError(f"invalid scope for batch mutation: {scope}")
