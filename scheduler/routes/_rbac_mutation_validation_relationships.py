from __future__ import annotations

from typing import Any, Dict

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


def _rbac_validate_device_group_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "device.group.set"
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

    group = logic.get_group(group_id)
    if group is None:
        raise ValueError(f"group not found: {group_id}")
    device = logic.get_device(device_id)
    if device is None:
        raise ValueError(f"device not found: {device_id}")

    linked = _rbac_json_bool(operation.get("linked", False), field="linked")
    existing = (
        model.db.session.get(model.DeviceGroup, (device.id, group.id)) is not None
    )
    expected_linked = _rbac_optional_json_bool(operation, field="expected_linked")
    if linked and not existing and (not group.active or not bool(group.department)):
        raise ValueError(f"group cannot be linked to devices: {group.id}")
    return {
        "kind": kind,
        "group": group,
        "device": device,
        "linked": linked,
        "expected_linked": bool(expected_linked)
        if expected_linked is not None
        else False,
        "has_expected_linked": expected_linked is not None,
    }


def _rbac_validate_user_device_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "user.device.set"
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

    templates = _rbac_json_bool(operation.get("templates", False), field="templates")
    slot = _rbac_json_bool(operation.get("slot", False), field="slot")
    tech = _rbac_json_bool(operation.get("tech", False), field="tech")
    medical = _rbac_json_bool(operation.get("medical", False), field="medical")
    training = _rbac_json_bool(operation.get("training", False), field="training")
    is_dev_member, is_technologist = logic.get_dev_tech_status(user)
    has_any_permission = any((templates, slot, tech, medical, training))

    expected_templates = _rbac_optional_json_bool(operation, field="expected_templates")
    expected_slot = _rbac_optional_json_bool(operation, field="expected_slot")
    expected_tech = _rbac_optional_json_bool(operation, field="expected_tech")
    expected_medical = _rbac_optional_json_bool(operation, field="expected_medical")
    expected_training = _rbac_optional_json_bool(operation, field="expected_training")
    expected_state_flags = (
        expected_templates is not None,
        expected_slot is not None,
        expected_tech is not None,
        expected_medical is not None,
        expected_training is not None,
    )
    if any(expected_state_flags) and not all(expected_state_flags):
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
        "expected_templates": bool(expected_templates)
        if expected_templates is not None
        else False,
        "expected_slot": bool(expected_slot) if expected_slot is not None else False,
        "expected_tech": bool(expected_tech) if expected_tech is not None else False,
        "expected_medical": bool(expected_medical)
        if expected_medical is not None
        else False,
        "expected_training": bool(expected_training)
        if expected_training is not None
        else False,
        "has_expected_permissions": all(expected_state_flags),
    }


def _rbac_validate_group_membership_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "group.membership.set"
    group_id = str(operation.get("group", "")).strip()
    user_id = str(operation.get("user", "")).strip()
    if group_id == "" or user_id == "":
        raise ValueError("group.membership.set requires group and user")
    if "pi" in operation:
        raise ValueError("group.membership.set no longer accepts pi; use group.pi.set")
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

    existing = model.db.session.get(model.GroupMember, (group.id, user.id))
    current_email_status = _rbac_email_status(
        existing.email_status if existing is not None else audit_logic.EMAIL_STATUS_NONE
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
        email_status = audit_logic.EMAIL_STATUS_NONE

    expected_member = _rbac_optional_json_bool(operation, field="expected_member")
    expected_approved = _rbac_optional_json_bool(operation, field="expected_approved")
    expected_email_status = _rbac_optional_json_email_status(
        operation,
        field="expected_email_status",
    )

    if member and not user.active:
        raise ValueError(f"only active users may be assigned membership: {user.id}")
    if not member and approved:
        raise ValueError("non-members cannot be approved")

    has_expected_member = expected_member is not None
    has_expected_approved = expected_approved is not None
    has_expected_email_status = expected_email_status is not None
    if has_expected_member != has_expected_approved:
        raise ValueError("expected_member and expected_approved must both be provided")
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
        "expected_approved": bool(expected_approved)
        if has_expected_approved
        else False,
        "has_expected_state": has_expected_member and has_expected_approved,
        "expected_email_status": expected_email_status or "",
        "has_expected_email_status": has_expected_email_status,
    }


def _rbac_validate_group_pi_set(
    operation: Dict[str, Any], *, scope: str, entity: str
) -> Dict[str, Any]:
    kind = "group.pi.set"
    group = _rbac_scoped_group(operation, scope=scope, entity=entity, kind=kind)
    if not group.active:
        raise ValueError(f"group is inactive: {group.id}")

    user_id = _rbac_json_string(
        operation.get("user", ""),
        field="user",
        required=True,
        max_length=20,
    )
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
    return {
        "kind": kind,
        "group": group,
        "user": user,
        "expected_current_pi": expected_current_pi or "",
        "has_expected_current_pi": expected_current_pi is not None,
    }


RELATIONSHIP_VALIDATORS = {
    "device.group.set": _rbac_validate_device_group_set,
    "user.device.set": _rbac_validate_user_device_set,
    "group.membership.set": _rbac_validate_group_membership_set,
    "group.pi.set": _rbac_validate_group_pi_set,
}
