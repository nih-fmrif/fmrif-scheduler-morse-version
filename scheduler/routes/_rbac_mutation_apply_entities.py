from __future__ import annotations

from typing import Any, Dict, List, Tuple

from flask import g
from sqlalchemy.sql import func

import scheduler.logic.notifications as notification_logic
import scheduler.logic.rbac_audit_support as audit_logic
from scheduler import model

from ._rbac_mutation_apply_support import (
    _rbac_apply_bool_update,
    _rbac_apply_text_update,
    _rbac_assert_expected_bool_field,
    _rbac_assert_expected_text_field,
    _rbac_badge,
    _rbac_state,
    _record_rbac_action,
)
from ._rbac_mutation_shared import (
    _rbac_audit_preview,
    _rbac_email_status,
    _RBACConflictError,
)


def _rbac_apply_group_create(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = model.Group(
        id=validated["group_id"],
        label=validated["label"],
        description=validated["description"],
        color=validated["color"],
        addr=validated["addr"],
        link=validated["link"],
        active=bool(validated["active"]),
        inst=validated["inst"] or None,
    )
    pi_user = validated["pi_user"]
    model.db.session.add(group)
    model.db.session.add(
        model.GroupMember(user=pi_user.id, group=group.id, approved=func.now())
    )
    model.db.session.add(model.PrimaryGroupMember(user=pi_user.id, group=group.id))
    _record_rbac_action(
        action="group.create",
        where=f"/group/{group.id}",
        how="rbac-explorer-batch",
        what=(
            f"group={group.id}, label={_rbac_audit_preview(group.label)}, "
            f"pi={pi_user.id}, active={_rbac_badge(bool(group.active))}"
        ),
        source_ip=source_ip,
    )
    return (f"Created group {group.id}.", True)


def _rbac_apply_device_create(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    device = model.Device(
        id=validated["device_id"],
        label=validated["label"],
        description=validated["description"],
        addr=validated["addr"],
        tech_addr=validated["tech_addr"],
        med_addr=validated["med_addr"],
        train_addr=validated["train_addr"],
        active=bool(validated["active"]),
    )
    model.db.session.add(device)
    _record_rbac_action(
        action="device.create",
        where=f"/device/{device.id}",
        how="rbac-explorer-batch",
        what=(
            f"device={device.id}, label={_rbac_audit_preview(device.label)}, "
            f"active={_rbac_badge(bool(device.active))}"
        ),
        source_ip=source_ip,
    )
    return (f"Created device {device.id}.", True)


def _rbac_apply_active_state(
    validated: Dict[str, Any],
    *,
    source_ip: str,
    entity_key: str,
    entity_label: str,
    action: str,
    where: str,
) -> Tuple[str, bool]:
    entity = validated[entity_key]
    active = bool(validated["active"])
    current_active = bool(entity.active)
    if bool(validated.get("has_expected_active")):
        expected_active = bool(validated.get("expected_active"))
        if current_active != expected_active:
            raise _RBACConflictError(
                f"{entity_label} active-state changed before apply for "
                f"{entity.id}: expected {_rbac_badge(expected_active)}, "
                f"current {_rbac_badge(current_active)}"
            )
    if current_active == active:
        return (f"{entity.id} is already {_rbac_state(active)}.", False)

    previous = current_active
    entity.active = active
    model.db.session.add(entity)
    _record_rbac_action(
        action=action,
        where=where,
        how="rbac-explorer-batch",
        what=(
            f"{entity_label}={entity.id}, "
            f"active={_rbac_badge(previous)}->{_rbac_badge(active)}"
        ),
        source_ip=source_ip,
    )
    return (f"Set {entity.id} to {_rbac_state(active)}.", True)


def _rbac_apply_group_active_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = validated["group"]
    return _rbac_apply_active_state(
        validated,
        source_ip=source_ip,
        entity_key="group",
        entity_label="group",
        action="group.update",
        where=f"/rbac?scope=group&entity={group.id}",
    )


def _rbac_apply_device_active_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    device = validated["device"]
    return _rbac_apply_active_state(
        validated,
        source_ip=source_ip,
        entity_key="device",
        entity_label="device",
        action="device.update",
        where=f"/rbac?scope=device&entity={device.id}",
    )


def _rbac_apply_user_active_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    user = validated["user"]
    return _rbac_apply_active_state(
        validated,
        source_ip=source_ip,
        entity_key="user",
        entity_label="user",
        action="user.update",
        where=f"/rbac?scope=user&entity={user.id}",
    )


def _rbac_apply_user_profile_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    user = validated["user"]
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_addr",
        expected_key="expected_addr",
        current_value=user.addr or "",
        entity_label="user profile",
        entity_id=user.id,
        field_label="addr",
    )
    addr = str(validated.get("addr", ""))
    if (user.addr or "") == addr:
        return (f"Profile for {user.id} already matches requested state.", False)

    previous_addr = user.addr or ""
    user.addr = addr
    model.db.session.add(user)
    _record_rbac_action(
        action="user.profile.update",
        where=f"/rbac?scope=user&entity={user.id}",
        how="rbac-explorer-batch",
        what=(
            f"user={user.id}, "
            f"addr={_rbac_audit_preview(previous_addr)}->{_rbac_audit_preview(addr)}"
        ),
        source_ip=source_ip,
    )
    return (f"Updated profile for {user.id}.", True)


def _rbac_apply_user_technologist_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    user = validated["user"]
    applied = bool(validated.get("applied"))
    approved = bool(validated.get("approved"))
    requested_email_status = _rbac_email_status(
        str(validated.get("email_status", audit_logic.EMAIL_STATUS_NONE))
    )
    set_email_status = bool(validated.get("set_email_status"))

    existing = model.db.session.get(model.Technologist, user.id)
    before_applied = existing is not None
    before_approved = (
        bool(existing.approved_on is not None) if existing is not None else False
    )
    before_email_status = _rbac_email_status(
        existing.email_status if existing is not None else audit_logic.EMAIL_STATUS_NONE
    )

    if bool(validated.get("has_expected_state")):
        expected_applied = bool(validated.get("expected_applied"))
        expected_approved = bool(validated.get("expected_approved"))
        if before_applied != expected_applied or before_approved != expected_approved:
            raise _RBACConflictError(
                "technologist state changed before apply for "
                f"{user.id}: expected applied={_rbac_badge(expected_applied)}, "
                f"approved={_rbac_badge(expected_approved)}; "
                f"current applied={_rbac_badge(before_applied)}, "
                f"approved={_rbac_badge(before_approved)}"
            )
    if bool(validated.get("has_expected_email_status")):
        expected_email_status = _rbac_email_status(
            str(validated.get("expected_email_status", audit_logic.EMAIL_STATUS_NONE))
        )
        if before_email_status != expected_email_status:
            raise _RBACConflictError(
                "technologist state changed before apply for "
                f"{user.id} email_status: "
                f"expected {expected_email_status}, current {before_email_status}"
            )

    row = existing
    resend_attempted = False
    resend_result = ""
    if applied:
        if row is None:
            row = model.Technologist(user=user.id)
        if row.applied_on is None:
            row.applied_on = func.now()
        if approved:
            if row.approved_on is None:
                row.approved_on = func.now()
            row.email_status = audit_logic.EMAIL_STATUS_NONE
        else:
            row.approved_on = None
            if (
                set_email_status
                and requested_email_status == audit_logic.EMAIL_STATUS_SENT
            ):
                resend_attempted = True
                resend_result = notification_logic.notify_dev_pi_of_tech_join_form(user)
                row.email_status = resend_result
            else:
                row.email_status = requested_email_status
        model.db.session.add(row)
        after_applied = True
        after_approved = bool(row.approved_on is not None)
        after_email_status = _rbac_email_status(row.email_status)
    else:
        if row is not None:
            model.db.session.delete(row)
        after_applied = False
        after_approved = False
        after_email_status = audit_logic.EMAIL_STATUS_NONE

    changed = (
        before_applied != after_applied
        or before_approved != after_approved
        or before_email_status != after_email_status
    )
    if not changed and not resend_attempted:
        return (
            f"Technologist state for {user.id} already matches requested state.",
            False,
        )

    _record_rbac_action(
        action="user.technologist.update",
        where=f"/rbac?scope=user&entity={user.id}",
        how="rbac-explorer-batch",
        what=(
            f"user={user.id}, "
            f"applied={_rbac_badge(before_applied)}->{_rbac_badge(after_applied)}, "
            f"approved={_rbac_badge(before_approved)}->{_rbac_badge(after_approved)}, "
            f"email_status={before_email_status}->{after_email_status}"
        ),
        source_ip=source_ip,
    )
    if (
        before_email_status == audit_logic.EMAIL_STATUS_FAILED
        and after_email_status != audit_logic.EMAIL_STATUS_FAILED
    ):
        audit_logic.log_email_issue_resolution(
            issue_key=f"join-tech:DEV:{user.id}",
            actor=g.user.id if g.user is not None else "unknown",
            where=f"/rbac?scope=user&entity={user.id}",
            how="rbac-explorer-batch",
            details=(
                f"group=DEV, requester={user.id}, "
                f"email_status={before_email_status}->{after_email_status}"
            ),
            source_ip=source_ip,
        )
    if resend_attempted:
        if resend_result == audit_logic.EMAIL_STATUS_SENT:
            return (
                f"Updated technologist state for {user.id} and resent request email.",
                True,
            )
        return (f"Updated technologist state for {user.id}; resend email failed.", True)
    return (f"Updated technologist state for {user.id}.", True)


def _rbac_apply_group_meta_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = validated["group"]
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_label",
        expected_key="expected_label",
        current_value=group.label or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="label",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_description",
        expected_key="expected_description",
        current_value=group.description or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="description",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_addr",
        expected_key="expected_addr",
        current_value=group.addr or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="addr",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_link",
        expected_key="expected_link",
        current_value=group.link or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="link",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_color",
        expected_key="expected_color",
        current_value=group.color or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="color",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_inst",
        expected_key="expected_inst",
        current_value=group.inst or "",
        entity_label="group metadata",
        entity_id=group.id,
        field_label="inst",
    )
    _rbac_assert_expected_bool_field(
        validated,
        has_key="has_expected_active",
        expected_key="expected_active",
        current_value=bool(group.active),
        entity_label="group metadata",
        entity_id=group.id,
        field_label="active",
    )

    changes: List[str] = []
    _rbac_apply_text_update(
        changes,
        group,
        attr="label",
        field_label="label",
        validated=validated,
        set_key="set_label",
        value_key="label",
    )
    _rbac_apply_text_update(
        changes,
        group,
        attr="description",
        field_label="description",
        validated=validated,
        set_key="set_description",
        value_key="description",
    )
    _rbac_apply_text_update(
        changes,
        group,
        attr="addr",
        field_label="addr",
        validated=validated,
        set_key="set_addr",
        value_key="addr",
    )
    _rbac_apply_text_update(
        changes,
        group,
        attr="link",
        field_label="link",
        validated=validated,
        set_key="set_link",
        value_key="link",
    )
    _rbac_apply_text_update(
        changes,
        group,
        attr="color",
        field_label="color",
        validated=validated,
        set_key="set_color",
        value_key="color",
    )
    _rbac_apply_text_update(
        changes,
        group,
        attr="inst",
        field_label="inst",
        validated=validated,
        set_key="set_inst",
        value_key="inst",
        transform=lambda value: value or None,
    )
    _rbac_apply_bool_update(
        changes,
        group,
        attr="active",
        field_label="active",
        validated=validated,
        set_key="set_active",
        value_key="active",
    )

    if len(changes) == 0:
        return (f"Metadata for {group.id} already matches requested state.", False)

    model.db.session.add(group)
    _record_rbac_action(
        action="group.update",
        where=f"/rbac?scope=group&entity={group.id}",
        how="rbac-explorer-batch",
        what=f"group={group.id}, {'; '.join(changes)}",
        source_ip=source_ip,
    )
    return (f"Updated metadata for {group.id}.", True)


def _rbac_apply_device_meta_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    device = validated["device"]
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_label",
        expected_key="expected_label",
        current_value=device.label or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="label",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_description",
        expected_key="expected_description",
        current_value=device.description or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="description",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_addr",
        expected_key="expected_addr",
        current_value=device.addr or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="addr",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_tech_addr",
        expected_key="expected_tech_addr",
        current_value=device.tech_addr or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="tech_addr",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_med_addr",
        expected_key="expected_med_addr",
        current_value=device.med_addr or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="med_addr",
    )
    _rbac_assert_expected_text_field(
        validated,
        has_key="has_expected_train_addr",
        expected_key="expected_train_addr",
        current_value=device.train_addr or "",
        entity_label="device metadata",
        entity_id=device.id,
        field_label="train_addr",
    )
    _rbac_assert_expected_bool_field(
        validated,
        has_key="has_expected_active",
        expected_key="expected_active",
        current_value=bool(device.active),
        entity_label="device metadata",
        entity_id=device.id,
        field_label="active",
    )

    changes: List[str] = []
    _rbac_apply_text_update(
        changes,
        device,
        attr="label",
        field_label="label",
        validated=validated,
        set_key="set_label",
        value_key="label",
    )
    _rbac_apply_text_update(
        changes,
        device,
        attr="description",
        field_label="description",
        validated=validated,
        set_key="set_description",
        value_key="description",
    )
    _rbac_apply_text_update(
        changes,
        device,
        attr="addr",
        field_label="addr",
        validated=validated,
        set_key="set_addr",
        value_key="addr",
    )
    _rbac_apply_text_update(
        changes,
        device,
        attr="tech_addr",
        field_label="tech_addr",
        validated=validated,
        set_key="set_tech_addr",
        value_key="tech_addr",
    )
    _rbac_apply_text_update(
        changes,
        device,
        attr="med_addr",
        field_label="med_addr",
        validated=validated,
        set_key="set_med_addr",
        value_key="med_addr",
    )
    _rbac_apply_text_update(
        changes,
        device,
        attr="train_addr",
        field_label="train_addr",
        validated=validated,
        set_key="set_train_addr",
        value_key="train_addr",
    )
    _rbac_apply_bool_update(
        changes,
        device,
        attr="active",
        field_label="active",
        validated=validated,
        set_key="set_active",
        value_key="active",
    )

    if len(changes) == 0:
        return (f"Metadata for {device.id} already matches requested state.", False)

    model.db.session.add(device)
    _record_rbac_action(
        action="device.update",
        where=f"/rbac?scope=device&entity={device.id}",
        how="rbac-explorer-batch",
        what=f"device={device.id}, {'; '.join(changes)}",
        source_ip=source_ip,
    )
    return (f"Updated metadata for {device.id}.", True)


ENTITY_APPLIERS = {
    "group.create": _rbac_apply_group_create,
    "device.create": _rbac_apply_device_create,
    "group.active.set": _rbac_apply_group_active_set,
    "device.active.set": _rbac_apply_device_active_set,
    "user.active.set": _rbac_apply_user_active_set,
    "user.profile.set": _rbac_apply_user_profile_set,
    "user.technologist.set": _rbac_apply_user_technologist_set,
    "group.meta.set": _rbac_apply_group_meta_set,
    "device.meta.set": _rbac_apply_device_meta_set,
}
