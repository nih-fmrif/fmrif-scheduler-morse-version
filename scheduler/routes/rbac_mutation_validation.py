from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy import select

from scheduler import logic, model

_RBAC_SCOPE_LABELS: Dict[str, str] = {
    "group": "groups",
    "device": "devices",
    "user": "users",
}
_RBAC_EMAIL_STATUS_OPTIONS: List[Dict[str, str]] = [
    {"value": logic.EMAIL_STATUS_NONE, "label": logic.EMAIL_STATUS_NONE},
    {"value": logic.EMAIL_STATUS_SENT, "label": logic.EMAIL_STATUS_SENT},
    {"value": logic.EMAIL_STATUS_FAILED, "label": logic.EMAIL_STATUS_FAILED},
]


def _rbac_email_status(value: str) -> str:
    normalized = (value or "").strip().lower()
    options = [opt["value"] for opt in _RBAC_EMAIL_STATUS_OPTIONS]
    if normalized in options:
        return normalized
    return logic.EMAIL_STATUS_NONE


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
    if token not in logic.EMAIL_STATUS_VALUES:
        raise ValueError(
            f"{field} must be one of: {', '.join(logic.EMAIL_STATUS_VALUES)}"
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


def _rbac_validate_batch_operation(
    operation: Dict[str, Any],
    *,
    scope: str,
    entity: str,
) -> Dict[str, Any]:
    kind = str(operation.get("kind", "")).strip()
    if kind == "":
        raise ValueError("operation kind is required")

    # Entity active-state toggles.
    if kind == "group.active.set":
        group_id = str(operation.get("group", "")).strip()
        if group_id == "":
            raise ValueError("group.active.set requires group")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        if group.id in {"admin", "DEV"} and not active:
            raise ValueError(f"special group cannot be deactivated: {group.id}")
        return {
            "kind": kind,
            "group": group,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "device.active.set":
        device_id = str(operation.get("device", "")).strip()
        if device_id == "":
            raise ValueError("device.active.set requires device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id="",
        )
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        return {
            "kind": kind,
            "device": device,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "user.active.set":
        user_id = str(operation.get("user", "")).strip()
        if user_id == "":
            raise ValueError("user.active.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id="",
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        return {
            "kind": kind,
            "user": user,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    # User profile and technologist request state.
    if kind == "user.profile.set":
        user_id = str(operation.get("user", "")).strip()
        if user_id == "":
            raise ValueError("user.profile.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id="",
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        if "addr" not in operation:
            raise ValueError("user.profile.set requires addr")
        addr = _rbac_json_string(operation.get("addr", user.addr), field="addr")
        expected_addr = _rbac_optional_json_string(operation, field="expected_addr")
        return {
            "kind": kind,
            "user": user,
            "addr": addr,
            "expected_addr": expected_addr if expected_addr is not None else "",
            "has_expected_addr": expected_addr is not None,
        }

    if kind == "user.technologist.set":
        user_id = str(operation.get("user", "")).strip()
        if user_id == "":
            raise ValueError("user.technologist.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id="",
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        applied = _rbac_json_bool(operation.get("applied", False), field="applied")
        approved = _rbac_json_bool(operation.get("approved", False), field="approved")
        if approved and not applied:
            raise ValueError("approved technologist state requires applied=true")
        is_dev_member, _ = logic.get_dev_tech_status(user)
        if applied and not is_dev_member:
            raise ValueError(f"user is not an active DEV member: {user.id}")
        current = model.get(model.Technologist, user.id)
        current_email_status = _rbac_email_status(
            current.email_status if current is not None else logic.EMAIL_STATUS_NONE
        )
        set_email_status = "email_status" in operation
        email_status = current_email_status
        if set_email_status:
            email_status = _rbac_json_email_status(
                operation.get("email_status"), field="email_status"
            )
        if not applied or approved:
            email_status = logic.EMAIL_STATUS_NONE
        expected_applied = _rbac_optional_json_bool(operation, field="expected_applied")
        expected_approved = _rbac_optional_json_bool(
            operation, field="expected_approved"
        )
        has_expected_applied = expected_applied is not None
        has_expected_approved = expected_approved is not None
        if has_expected_applied != has_expected_approved:
            raise ValueError(
                "expected_applied and expected_approved must both be provided"
            )
        expected_email_status = _rbac_optional_json_email_status(
            operation, field="expected_email_status"
        )
        has_expected_email_status = expected_email_status is not None
        if has_expected_email_status and not has_expected_applied:
            raise ValueError(
                "expected_email_status requires expected_applied and expected_approved"
            )
        if bool(expected_approved) and not bool(expected_applied):
            raise ValueError("expected approved technologist state requires applied")
        if bool(expected_applied) is False and expected_email_status not in {
            None,
            "none",
        }:
            raise ValueError(
                "expected non-applied technologist rows must use email_status=none"
            )
        return {
            "kind": kind,
            "user": user,
            "applied": applied,
            "approved": approved,
            "email_status": email_status,
            "set_email_status": set_email_status,
            "expected_applied": (
                bool(expected_applied) if has_expected_applied else False
            ),
            "expected_approved": (
                bool(expected_approved) if has_expected_approved else False
            ),
            "has_expected_state": has_expected_applied and has_expected_approved,
            "expected_email_status": (
                expected_email_status if expected_email_status is not None else ""
            ),
            "has_expected_email_status": has_expected_email_status,
        }

    # Entity creation.
    if kind == "group.create":
        if scope != "group":
            raise ValueError("group.create must use group scope")
        group_id = _rbac_json_string(
            operation.get("group", ""),
            field="group",
            required=True,
            max_length=10,
        )
        if group_id in {"admin", "DEV"}:
            raise ValueError(f"group id is reserved: {group_id}")
        if logic.get_group(group_id) is not None:
            raise ValueError(f"group already exists: {group_id}")

        label = _rbac_json_string(
            operation.get("label", ""),
            field="label",
            required=True,
            max_length=20,
        )
        existing_short = model.db.session.scalars(
            select(model.Group).where(model.Group.label == label)
        ).first()
        if existing_short is not None:
            raise ValueError(f"group short label already in use: {label}")

        description = _rbac_json_string(
            operation.get("description", ""),
            field="description",
            required=True,
            max_length=75,
        )
        existing_long = model.db.session.scalars(
            select(model.Group).where(model.Group.description == description)
        ).first()
        if existing_long is not None:
            raise ValueError(f"group description already in use: {description}")

        pi_id = _rbac_json_string(
            operation.get("pi", ""),
            field="pi",
            required=True,
            max_length=20,
        )
        pi_user = logic.get_user(pi_id)
        if pi_user is None:
            raise ValueError(f"user not found: {pi_id}")
        if not pi_user.active:
            raise ValueError(f"only active users may be PI: {pi_id}")

        addr = _rbac_json_string(operation.get("addr", ""), field="addr")
        link = _rbac_json_string(operation.get("link", ""), field="link")
        _rbac_validate_optional_url(link, field="link")

        color = _rbac_json_string(
            operation.get("color", "#000000"),
            field="color",
            required=True,
            max_length=7,
        )
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
            raise ValueError("color must be a hex value like #1a2b3c")

        inst = _rbac_json_string(
            operation.get("inst", ""),
            field="inst",
            max_length=7,
        )
        if inst != "" and model.get(model.Inst, inst) is None:
            raise ValueError(f"institute not found: {inst}")

        active = _rbac_json_bool(operation.get("active", True), field="active")
        return {
            "kind": kind,
            "group_id": group_id,
            "label": label,
            "description": description,
            "pi_user": pi_user,
            "addr": addr,
            "link": link,
            "color": color,
            "inst": inst,
            "active": active,
        }

    if kind == "device.create":
        if scope != "device":
            raise ValueError("device.create must use device scope")
        device_id = _rbac_json_string(
            operation.get("device", ""),
            field="device",
            required=True,
            max_length=5,
        )
        if logic.get_device(device_id) is not None:
            raise ValueError(f"device already exists: {device_id}")

        label = _rbac_json_string(
            operation.get("label", ""),
            field="label",
            required=True,
            max_length=25,
        )
        existing_label = model.db.session.scalars(
            select(model.Device).where(model.Device.label == label)
        ).first()
        if existing_label is not None:
            raise ValueError(f"device label already in use: {label}")

        description = _rbac_json_string(
            operation.get("description", ""),
            field="description",
        )
        addr = _rbac_json_string(operation.get("addr", ""), field="addr")
        tech_addr = _rbac_json_string(
            operation.get("tech_addr", ""),
            field="tech_addr",
        )
        med_addr = _rbac_json_string(
            operation.get("med_addr", ""),
            field="med_addr",
        )
        train_addr = _rbac_json_string(
            operation.get("train_addr", ""),
            field="train_addr",
        )
        active = _rbac_json_bool(operation.get("active", True), field="active")
        return {
            "kind": kind,
            "device_id": device_id,
            "label": label,
            "description": description,
            "addr": addr,
            "tech_addr": tech_addr,
            "med_addr": med_addr,
            "train_addr": train_addr,
            "active": active,
        }

    # Group and device metadata edits.
    if kind == "group.meta.set":
        group_id = str(operation.get("group", "")).strip()
        if group_id == "":
            raise ValueError("group.meta.set requires group")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        set_label = "label" in operation
        set_description = "description" in operation
        set_addr = "addr" in operation
        set_link = "link" in operation
        set_color = "color" in operation
        set_inst = "inst" in operation
        set_active = "active" in operation

        label = _rbac_json_string(
            operation.get("label", group.label),
            field="label",
            required=True,
            max_length=20,
        )
        description = _rbac_json_string(
            operation.get("description", group.description),
            field="description",
            required=True,
            max_length=75,
        )
        addr = _rbac_json_string(
            operation.get("addr", group.addr),
            field="addr",
        )
        link = _rbac_json_string(
            operation.get("link", group.link),
            field="link",
        )
        _rbac_validate_optional_url(link, field="link")

        color = _rbac_json_string(
            operation.get("color", group.color),
            field="color",
            max_length=7,
        )
        if color != "" and re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
            raise ValueError("color must be a hex value like #1a2b3c")

        inst = _rbac_json_string(
            operation.get("inst", group.inst or ""),
            field="inst",
            max_length=7,
        )
        if inst != "" and model.get(model.Inst, inst) is None:
            raise ValueError(f"institute not found: {inst}")
        active = _rbac_json_bool(operation.get("active", group.active), field="active")

        special_group = group.id in {"admin", "DEV"}
        if special_group and not active:
            raise ValueError(f"special group cannot be deactivated: {group.id}")
        if special_group:
            color = group.color or "#000000"
            inst = group.inst or ""

        expected_label = _rbac_optional_json_string(
            operation,
            field="expected_label",
            max_length=20,
        )
        expected_description = _rbac_optional_json_string(
            operation,
            field="expected_description",
            max_length=75,
        )
        expected_addr = _rbac_optional_json_string(operation, field="expected_addr")
        expected_link = _rbac_optional_json_string(operation, field="expected_link")
        expected_color = _rbac_optional_json_string(
            operation,
            field="expected_color",
            max_length=7,
        )
        expected_inst = _rbac_optional_json_string(
            operation,
            field="expected_inst",
            max_length=7,
        )
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")

        return {
            "kind": kind,
            "group": group,
            "label": label,
            "description": description,
            "addr": addr,
            "link": link,
            "color": color,
            "inst": inst,
            "active": active,
            "special_group": special_group,
            "set_label": set_label,
            "set_description": set_description,
            "set_addr": set_addr,
            "set_link": set_link,
            "set_color": set_color,
            "set_inst": set_inst,
            "set_active": set_active,
            "expected_label": expected_label if expected_label is not None else "",
            "has_expected_label": expected_label is not None,
            "expected_description": (
                expected_description if expected_description is not None else ""
            ),
            "has_expected_description": expected_description is not None,
            "expected_addr": expected_addr if expected_addr is not None else "",
            "has_expected_addr": expected_addr is not None,
            "expected_link": expected_link if expected_link is not None else "",
            "has_expected_link": expected_link is not None,
            "expected_color": expected_color if expected_color is not None else "",
            "has_expected_color": expected_color is not None,
            "expected_inst": expected_inst if expected_inst is not None else "",
            "has_expected_inst": expected_inst is not None,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "device.meta.set":
        device_id = str(operation.get("device", "")).strip()
        if device_id == "":
            raise ValueError("device.meta.set requires device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id="",
        )
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        set_label = "label" in operation
        set_description = "description" in operation
        set_addr = "addr" in operation
        set_tech_addr = "tech_addr" in operation
        set_med_addr = "med_addr" in operation
        set_train_addr = "train_addr" in operation
        set_active = "active" in operation

        label = _rbac_json_string(
            operation.get("label", device.label),
            field="label",
            required=True,
            max_length=25,
        )
        description = _rbac_json_string(
            operation.get("description", device.description),
            field="description",
        )
        addr = _rbac_json_string(
            operation.get("addr", device.addr),
            field="addr",
        )
        tech_addr = _rbac_json_string(
            operation.get("tech_addr", device.tech_addr),
            field="tech_addr",
        )
        med_addr = _rbac_json_string(
            operation.get("med_addr", device.med_addr),
            field="med_addr",
        )
        train_addr = _rbac_json_string(
            operation.get("train_addr", device.train_addr),
            field="train_addr",
        )
        active = _rbac_json_bool(operation.get("active", device.active), field="active")
        expected_label = _rbac_optional_json_string(
            operation,
            field="expected_label",
            max_length=25,
        )
        expected_description = _rbac_optional_json_string(
            operation,
            field="expected_description",
        )
        expected_addr = _rbac_optional_json_string(operation, field="expected_addr")
        expected_tech_addr = _rbac_optional_json_string(
            operation,
            field="expected_tech_addr",
        )
        expected_med_addr = _rbac_optional_json_string(
            operation,
            field="expected_med_addr",
        )
        expected_train_addr = _rbac_optional_json_string(
            operation,
            field="expected_train_addr",
        )
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")

        return {
            "kind": kind,
            "device": device,
            "label": label,
            "description": description,
            "addr": addr,
            "tech_addr": tech_addr,
            "med_addr": med_addr,
            "train_addr": train_addr,
            "active": active,
            "set_label": set_label,
            "set_description": set_description,
            "set_addr": set_addr,
            "set_tech_addr": set_tech_addr,
            "set_med_addr": set_med_addr,
            "set_train_addr": set_train_addr,
            "set_active": set_active,
            "expected_label": expected_label if expected_label is not None else "",
            "has_expected_label": expected_label is not None,
            "expected_description": (
                expected_description if expected_description is not None else ""
            ),
            "has_expected_description": expected_description is not None,
            "expected_addr": expected_addr if expected_addr is not None else "",
            "has_expected_addr": expected_addr is not None,
            "expected_tech_addr": (
                expected_tech_addr if expected_tech_addr is not None else ""
            ),
            "has_expected_tech_addr": expected_tech_addr is not None,
            "expected_med_addr": expected_med_addr
            if expected_med_addr is not None
            else "",
            "has_expected_med_addr": expected_med_addr is not None,
            "expected_train_addr": (
                expected_train_addr if expected_train_addr is not None else ""
            ),
            "has_expected_train_addr": expected_train_addr is not None,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    # Relationship and permission links.
    if kind == "device.group.set":
        group_id = str(operation.get("group", "")).strip()
        device_id = str(operation.get("device", "")).strip()
        if group_id == "" or device_id == "":
            raise ValueError("device.group.set requires group and device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id=device_id,
            user_id="",
        )
        linked = _rbac_json_bool(operation.get("linked", False), field="linked")
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        existing = model.get(model.DeviceGroup, (device.id, group.id)) is not None
        expected_linked = _rbac_optional_json_bool(operation, field="expected_linked")
        if linked and not existing and (not group.active or not bool(group.department)):
            raise ValueError(f"group cannot be linked to devices: {group.id}")
        return {
            "kind": kind,
            "group": group,
            "device": device,
            "linked": linked,
            "existing": existing,
            "expected_linked": (
                bool(expected_linked) if expected_linked is not None else False
            ),
            "has_expected_linked": expected_linked is not None,
        }

    if kind == "user.device.set":
        user_id = str(operation.get("user", "")).strip()
        device_id = str(operation.get("device", "")).strip()
        if user_id == "" or device_id == "":
            raise ValueError("user.device.set requires user and device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")

        templates = _rbac_json_bool(
            operation.get("templates", False), field="templates"
        )
        slot = _rbac_json_bool(operation.get("slot", False), field="slot")
        tech = _rbac_json_bool(operation.get("tech", False), field="tech")
        medical = _rbac_json_bool(operation.get("medical", False), field="medical")
        training = _rbac_json_bool(operation.get("training", False), field="training")
        is_dev_member, is_technologist = logic.get_dev_tech_status(user)
        has_any_permission = any((templates, slot, tech, medical, training))
        expected_templates = _rbac_optional_json_bool(
            operation,
            field="expected_templates",
        )
        expected_slot = _rbac_optional_json_bool(operation, field="expected_slot")
        expected_tech = _rbac_optional_json_bool(operation, field="expected_tech")
        expected_medical = _rbac_optional_json_bool(operation, field="expected_medical")
        expected_training = _rbac_optional_json_bool(
            operation,
            field="expected_training",
        )
        expected_state_flags = (
            expected_templates is not None,
            expected_slot is not None,
            expected_tech is not None,
            expected_medical is not None,
            expected_training is not None,
        )
        has_any_expected_permission = any(expected_state_flags)
        has_full_expected_permission = all(expected_state_flags)
        if has_any_expected_permission and not has_full_expected_permission:
            raise ValueError(
                "expected_templates, expected_slot, expected_tech, "
                "expected_medical, and expected_training must all be provided"
            )

        if has_any_permission:
            if not user.active:
                raise ValueError(f"active user not found: {user.id}")
            if not is_dev_member:
                raise ValueError(f"user is not an active DEV member: {user.id}")
            if tech and not is_technologist:
                raise ValueError(f"user is not a technologist: {user.id}")

        return {
            "kind": kind,
            "user": user,
            "device": device,
            "templates": templates,
            "slot": slot,
            "tech": tech,
            "medical": medical,
            "training": training,
            "has_any_permission": has_any_permission,
            "is_technologist": is_technologist,
            "expected_templates": (
                bool(expected_templates) if expected_templates is not None else False
            ),
            "expected_slot": bool(expected_slot)
            if expected_slot is not None
            else False,
            "expected_tech": bool(expected_tech)
            if expected_tech is not None
            else False,
            "expected_medical": (
                bool(expected_medical) if expected_medical is not None else False
            ),
            "expected_training": (
                bool(expected_training) if expected_training is not None else False
            ),
            "has_expected_permissions": has_full_expected_permission,
        }

    # Group membership and PI assignment.
    if kind == "group.membership.set":
        group_id = str(operation.get("group", "")).strip()
        user_id = str(operation.get("user", "")).strip()
        if group_id == "" or user_id == "":
            raise ValueError("group.membership.set requires group and user")
        if "pi" in operation:
            raise ValueError(
                "group.membership.set no longer accepts pi; use group.pi.set"
            )
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id=user_id,
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        if not group.active:
            raise ValueError(f"group is inactive: {group_id}")
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        existing = model.get(model.GroupMember, (group.id, user.id))
        current_email_status = _rbac_email_status(
            existing.email_status if existing is not None else logic.EMAIL_STATUS_NONE
        )
        member = _rbac_json_bool(operation.get("member", False), field="member")
        approved = _rbac_json_bool(operation.get("approved", False), field="approved")
        set_email_status = "email_status" in operation
        email_status = current_email_status
        if member and not approved and set_email_status:
            email_status = _rbac_json_email_status(
                operation.get("email_status"), field="email_status"
            )
        if not member or approved:
            email_status = logic.EMAIL_STATUS_NONE
        expected_member = _rbac_optional_json_bool(
            operation,
            field="expected_member",
        )
        expected_approved = _rbac_optional_json_bool(
            operation,
            field="expected_approved",
        )
        expected_email_status = _rbac_optional_json_email_status(
            operation, field="expected_email_status"
        )
        if member and not user.active:
            raise ValueError(f"only active users may be assigned membership: {user.id}")
        if not member and approved:
            raise ValueError("non-members cannot be approved")
        has_expected_member = expected_member is not None
        has_expected_approved = expected_approved is not None
        has_expected_email_status = expected_email_status is not None
        if has_expected_member != has_expected_approved:
            raise ValueError(
                "expected_member and expected_approved must both be provided"
            )
        if has_expected_email_status and not has_expected_member:
            raise ValueError(
                "expected_email_status requires expected_member and expected_approved"
            )
        if expected_member is False and expected_approved:
            raise ValueError("expected non-members cannot be approved")
        if expected_member is False and expected_email_status not in {None, "none"}:
            raise ValueError("expected non-members must use expected_email_status=none")
        return {
            "kind": kind,
            "group": group,
            "user": user,
            "member": member,
            "approved": approved,
            "email_status": email_status,
            "set_email_status": set_email_status,
            "expected_member": bool(expected_member) if has_expected_member else False,
            "expected_approved": (
                bool(expected_approved) if has_expected_approved else False
            ),
            "has_expected_state": has_expected_member and has_expected_approved,
            "expected_email_status": (
                expected_email_status if expected_email_status is not None else ""
            ),
            "has_expected_email_status": has_expected_email_status,
        }

    if kind == "group.pi.set":
        group_id = str(operation.get("group", "")).strip()
        user_id = str(operation.get("user", "")).strip()
        if group_id == "":
            raise ValueError("group.pi.set requires group")
        if user_id == "":
            raise ValueError("group.pi.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        if not group.active:
            raise ValueError(f"group is inactive: {group_id}")
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        if not user.active:
            raise ValueError(f"only active users may be PI: {user.id}")
        expected_current_pi = _rbac_optional_json_string(
            operation,
            field="expected_current_pi",
            max_length=20,
        )
        if expected_current_pi is None:
            expected_current_pi = _rbac_optional_json_string(
                operation,
                field="expected_user",
                max_length=20,
            )
        has_expected_current_pi = expected_current_pi is not None
        return {
            "kind": kind,
            "group": group,
            "user": user,
            "expected_current_pi": expected_current_pi or "",
            "has_expected_current_pi": has_expected_current_pi,
        }

    raise ValueError(f"unsupported operation kind: {kind}")
