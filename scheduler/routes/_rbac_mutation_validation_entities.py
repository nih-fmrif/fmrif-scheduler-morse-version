from __future__ import annotations

import re
from typing import Any, Dict

from sqlalchemy import select

import scheduler.logic.core as logic
import scheduler.logic.rbac_audit_support as audit_logic
from scheduler import model

from ._rbac_mutation_shared import (
    _rbac_email_status,
    _rbac_json_bool,
    _rbac_json_email_status,
    _rbac_json_string,
    _rbac_optional_json_bool,
    _rbac_optional_json_email_status,
    _rbac_optional_json_string,
    _rbac_validate_operation_scope,
    _rbac_validate_optional_url,
)


def _rbac_scoped_group(
    operation: Dict[str, Any], *, scope: str, entity: str, kind: str
) -> model.Group:
    group_id = str(operation.get("group", "")).strip()
    if group_id == "":
        raise ValueError(f"{kind} requires group")
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
    return group


def _rbac_scoped_device(
    operation: Dict[str, Any], *, scope: str, entity: str, kind: str
) -> model.Device:
    device_id = str(operation.get("device", "")).strip()
    if device_id == "":
        raise ValueError(f"{kind} requires device")
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
    return device


def _rbac_scoped_user(
    operation: Dict[str, Any], *, scope: str, entity: str, kind: str
) -> model.User:
    user_id = str(operation.get("user", "")).strip()
    if user_id == "":
        raise ValueError(f"{kind} requires user")
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
    return user


def _rbac_validate_group_active_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "group.active.set"
    group = _rbac_scoped_group(operation, scope=scope, entity=entity, kind=kind)
    active = _rbac_json_bool(operation.get("active", True), field="active")
    expected_active = _rbac_optional_json_bool(operation, field="expected_active")
    if group.id in {"admin", "DEV"} and not active:
        raise ValueError(f"special group cannot be deactivated: {group.id}")
    return {
        "kind": kind,
        "group": group,
        "active": active,
        "expected_active": bool(expected_active)
        if expected_active is not None
        else False,
        "has_expected_active": expected_active is not None,
    }


def _rbac_validate_device_active_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "device.active.set"
    device = _rbac_scoped_device(operation, scope=scope, entity=entity, kind=kind)
    active = _rbac_json_bool(operation.get("active", True), field="active")
    expected_active = _rbac_optional_json_bool(operation, field="expected_active")
    return {
        "kind": kind,
        "device": device,
        "active": active,
        "expected_active": bool(expected_active)
        if expected_active is not None
        else False,
        "has_expected_active": expected_active is not None,
    }


def _rbac_validate_user_active_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "user.active.set"
    user = _rbac_scoped_user(operation, scope=scope, entity=entity, kind=kind)
    active = _rbac_json_bool(operation.get("active", True), field="active")
    expected_active = _rbac_optional_json_bool(operation, field="expected_active")
    return {
        "kind": kind,
        "user": user,
        "active": active,
        "expected_active": bool(expected_active)
        if expected_active is not None
        else False,
        "has_expected_active": expected_active is not None,
    }


def _rbac_validate_user_profile_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "user.profile.set"
    user = _rbac_scoped_user(operation, scope=scope, entity=entity, kind=kind)
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


def _rbac_validate_user_technologist_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "user.technologist.set"
    user = _rbac_scoped_user(operation, scope=scope, entity=entity, kind=kind)
    applied = _rbac_json_bool(operation.get("applied", False), field="applied")
    approved = _rbac_json_bool(operation.get("approved", False), field="approved")
    if approved and not applied:
        raise ValueError("approved technologist state requires applied=true")

    is_dev_member, _ = logic.get_dev_tech_status(user)
    if applied and not is_dev_member:
        raise ValueError(f"user is not an active DEV member: {user.id}")

    current = model.db.session.get(model.Technologist, user.id)
    current_email_status = _rbac_email_status(
        current.email_status if current is not None else audit_logic.EMAIL_STATUS_NONE
    )
    set_email_status = "email_status" in operation
    email_status = current_email_status
    if set_email_status:
        email_status = _rbac_json_email_status(
            operation.get("email_status"), field="email_status"
        )
    if not applied or approved:
        email_status = audit_logic.EMAIL_STATUS_NONE

    expected_applied = _rbac_optional_json_bool(operation, field="expected_applied")
    expected_approved = _rbac_optional_json_bool(operation, field="expected_approved")
    has_expected_applied = expected_applied is not None
    has_expected_approved = expected_approved is not None
    if has_expected_applied != has_expected_approved:
        raise ValueError("expected_applied and expected_approved must both be provided")

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
    if bool(expected_applied) is False and expected_email_status not in {None, "none"}:
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
        "expected_applied": bool(expected_applied) if has_expected_applied else False,
        "expected_approved": bool(expected_approved)
        if has_expected_approved
        else False,
        "has_expected_state": has_expected_applied and has_expected_approved,
        "expected_email_status": expected_email_status or "",
        "has_expected_email_status": has_expected_email_status,
    }


def _rbac_validate_group_create(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    del entity
    kind = "group.create"
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

    inst = _rbac_json_string(operation.get("inst", ""), field="inst", max_length=7)
    if inst != "" and model.db.session.get(model.Inst, inst) is None:
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


def _rbac_validate_device_create(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    del entity
    kind = "device.create"
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

    return {
        "kind": kind,
        "device_id": device_id,
        "label": label,
        "description": _rbac_json_string(
            operation.get("description", ""),
            field="description",
        ),
        "addr": _rbac_json_string(operation.get("addr", ""), field="addr"),
        "tech_addr": _rbac_json_string(
            operation.get("tech_addr", ""),
            field="tech_addr",
        ),
        "med_addr": _rbac_json_string(
            operation.get("med_addr", ""),
            field="med_addr",
        ),
        "train_addr": _rbac_json_string(
            operation.get("train_addr", ""),
            field="train_addr",
        ),
        "active": _rbac_json_bool(operation.get("active", True), field="active"),
    }


def _rbac_validate_group_meta_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "group.meta.set"
    group = _rbac_scoped_group(operation, scope=scope, entity=entity, kind=kind)

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
    addr = _rbac_json_string(operation.get("addr", group.addr), field="addr")
    link = _rbac_json_string(operation.get("link", group.link), field="link")
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
    if inst != "" and model.db.session.get(model.Inst, inst) is None:
        raise ValueError(f"institute not found: {inst}")
    active = _rbac_json_bool(operation.get("active", group.active), field="active")

    if group.id in {"admin", "DEV"}:
        if not active:
            raise ValueError(f"special group cannot be deactivated: {group.id}")
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
        "set_label": set_label,
        "set_description": set_description,
        "set_addr": set_addr,
        "set_link": set_link,
        "set_color": set_color,
        "set_inst": set_inst,
        "set_active": set_active,
        "expected_label": expected_label or "",
        "has_expected_label": expected_label is not None,
        "expected_description": expected_description or "",
        "has_expected_description": expected_description is not None,
        "expected_addr": expected_addr or "",
        "has_expected_addr": expected_addr is not None,
        "expected_link": expected_link or "",
        "has_expected_link": expected_link is not None,
        "expected_color": expected_color or "",
        "has_expected_color": expected_color is not None,
        "expected_inst": expected_inst or "",
        "has_expected_inst": expected_inst is not None,
        "expected_active": bool(expected_active)
        if expected_active is not None
        else False,
        "has_expected_active": expected_active is not None,
    }


def _rbac_validate_device_meta_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "device.meta.set"
    device = _rbac_scoped_device(operation, scope=scope, entity=entity, kind=kind)

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
        "label": _rbac_json_string(
            operation.get("label", device.label),
            field="label",
            required=True,
            max_length=25,
        ),
        "description": _rbac_json_string(
            operation.get("description", device.description),
            field="description",
        ),
        "addr": _rbac_json_string(operation.get("addr", device.addr), field="addr"),
        "tech_addr": _rbac_json_string(
            operation.get("tech_addr", device.tech_addr),
            field="tech_addr",
        ),
        "med_addr": _rbac_json_string(
            operation.get("med_addr", device.med_addr),
            field="med_addr",
        ),
        "train_addr": _rbac_json_string(
            operation.get("train_addr", device.train_addr),
            field="train_addr",
        ),
        "active": _rbac_json_bool(
            operation.get("active", device.active), field="active"
        ),
        "set_label": "label" in operation,
        "set_description": "description" in operation,
        "set_addr": "addr" in operation,
        "set_tech_addr": "tech_addr" in operation,
        "set_med_addr": "med_addr" in operation,
        "set_train_addr": "train_addr" in operation,
        "set_active": "active" in operation,
        "expected_label": expected_label or "",
        "has_expected_label": expected_label is not None,
        "expected_description": expected_description or "",
        "has_expected_description": expected_description is not None,
        "expected_addr": expected_addr or "",
        "has_expected_addr": expected_addr is not None,
        "expected_tech_addr": expected_tech_addr or "",
        "has_expected_tech_addr": expected_tech_addr is not None,
        "expected_med_addr": expected_med_addr or "",
        "has_expected_med_addr": expected_med_addr is not None,
        "expected_train_addr": expected_train_addr or "",
        "has_expected_train_addr": expected_train_addr is not None,
        "expected_active": bool(expected_active)
        if expected_active is not None
        else False,
        "has_expected_active": expected_active is not None,
    }


ENTITY_VALIDATORS = {
    "group.active.set": _rbac_validate_group_active_set,
    "device.active.set": _rbac_validate_device_active_set,
    "user.active.set": _rbac_validate_user_active_set,
    "user.profile.set": _rbac_validate_user_profile_set,
    "user.technologist.set": _rbac_validate_user_technologist_set,
    "group.create": _rbac_validate_group_create,
    "device.create": _rbac_validate_device_create,
    "group.meta.set": _rbac_validate_group_meta_set,
    "device.meta.set": _rbac_validate_device_meta_set,
}
