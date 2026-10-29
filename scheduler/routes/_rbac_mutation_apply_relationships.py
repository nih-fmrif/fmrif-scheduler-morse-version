from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import g
from sqlalchemy import select
from sqlalchemy.sql import func

import scheduler.logic.core as core_logic
import scheduler.logic.notifications as notification_logic
import scheduler.logic.rbac_audit_support as audit_logic
from scheduler import model

from ._rbac_mutation_apply_support import _rbac_badge, _record_rbac_action
from ._rbac_mutation_shared import (
    _rbac_email_status,
    _rbac_permission_flags,
    _RBACConflictError,
)


def _rbac_apply_device_group_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = validated["group"]
    device = validated["device"]
    linked = bool(validated["linked"])
    existing = model.db.session.get(model.DeviceGroup, (device.id, group.id))
    before_linked = existing is not None

    if bool(validated.get("has_expected_linked")):
        expected_linked = bool(validated.get("expected_linked"))
        if before_linked != expected_linked:
            raise _RBACConflictError(
                "device/group link changed before apply for "
                f"{device.id}/{group.id}: "
                f"expected linked={_rbac_badge(expected_linked)}, "
                f"current linked={_rbac_badge(before_linked)}"
            )

    if linked:
        if before_linked:
            return (f"{group.id} is already linked to {device.id}.", False)
        model.db.session.add(model.DeviceGroup(group=group.id, device=device.id))
        _record_rbac_action(
            action="device.group.add",
            where=f"/rbac?scope=device&entity={device.id}",
            how="rbac-explorer-batch",
            what=f"device={device.id}, group={group.id}",
            source_ip=source_ip,
        )
        return (f"Linked {group.id} to {device.id}.", True)

    if not before_linked:
        return (f"{group.id} is not linked to {device.id}.", False)
    model.db.session.delete(existing)
    _record_rbac_action(
        action="device.group.remove",
        where=f"/rbac?scope=device&entity={device.id}",
        how="rbac-explorer-batch",
        what=f"device={device.id}, group={group.id}",
        source_ip=source_ip,
    )
    return (f"Unlinked {group.id} from {device.id}.", True)


def _rbac_apply_user_device_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    user = validated["user"]
    device = validated["device"]
    templates = bool(validated["templates"])
    slot = bool(validated["slot"])
    tech = bool(validated["tech"]) and bool(validated["is_technologist"])
    medical = bool(validated["medical"])
    training = bool(validated["training"])
    has_any_permission = bool(validated["has_any_permission"])

    existing = model.db.session.get(model.UserDevice, (user.id, device.id))
    before = (
        (
            bool(existing.templates),
            bool(existing.slot),
            bool(existing.tech),
            bool(existing.medical),
            bool(existing.training),
        )
        if existing is not None
        else (False, False, False, False, False)
    )
    if bool(validated.get("has_expected_permissions")):
        expected = (
            bool(validated.get("expected_templates")),
            bool(validated.get("expected_slot")),
            bool(validated.get("expected_tech")),
            bool(validated.get("expected_medical")),
            bool(validated.get("expected_training")),
        )
        if before != expected:
            raise _RBACConflictError(
                "user/device permissions changed before apply for "
                f"{user.id}/{device.id}: "
                f"expected templates={_rbac_badge(expected[0])}, "
                f"slot={_rbac_badge(expected[1])}, "
                f"tech={_rbac_badge(expected[2])}, "
                f"medical={_rbac_badge(expected[3])}, "
                f"training={_rbac_badge(expected[4])}; "
                f"current templates={_rbac_badge(before[0])}, "
                f"slot={_rbac_badge(before[1])}, "
                f"tech={_rbac_badge(before[2])}, "
                f"medical={_rbac_badge(before[3])}, "
                f"training={_rbac_badge(before[4])}"
            )

    if has_any_permission:
        after = (templates, slot, tech, medical, training)
        if before == after:
            return (
                f"Permissions for {user.id} on {device.id} already match requested state.",
                False,
            )
        row = existing
        if row is None:
            row = model.UserDevice(user=user.id, device=device.id)
        row.templates = templates
        row.slot = slot
        row.tech = tech
        row.medical = medical
        row.training = training
        model.db.session.add(row)
        _record_rbac_action(
            action="user.device.update",
            where=f"/rbac?scope=user&entity={user.id}",
            how="rbac-explorer-batch",
            what=(
                f"device={device.id}, user={user.id}, "
                f"permissions={_rbac_permission_flags(row)}"
            ),
            source_ip=source_ip,
        )
        return (
            f"Updated device-specific permissions for {user.id} on {device.id}.",
            True,
        )

    if existing is None:
        return (f"{user.id} has no device-specific permissions on {device.id}.", False)
    model.db.session.delete(existing)
    _record_rbac_action(
        action="user.device.remove",
        where=f"/rbac?scope=user&entity={user.id}",
        how="rbac-explorer-batch",
        what=f"device={device.id}, user={user.id}",
        source_ip=source_ip,
    )
    return (f"Removed device-specific permissions for {user.id} on {device.id}.", True)


def _rbac_apply_group_membership_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = validated["group"]
    user = validated["user"]
    member = bool(validated["member"])
    approved = bool(validated["approved"])
    requested_email_status = _rbac_email_status(
        str(validated.get("email_status", audit_logic.EMAIL_STATUS_NONE))
    )
    set_email_status = bool(validated.get("set_email_status"))

    existing = model.db.session.get(model.GroupMember, (group.id, user.id))
    was_member = existing is not None
    was_approved = (
        bool(existing.approved is not None) if existing is not None else False
    )
    before_email_status = _rbac_email_status(
        existing.email_status if existing is not None else audit_logic.EMAIL_STATUS_NONE
    )
    before = (was_member, was_approved, before_email_status)

    if bool(validated.get("has_expected_state")):
        expected = (
            bool(validated.get("expected_member")),
            bool(validated.get("expected_approved")),
        )
        if expected[0] is False:
            expected = (False, False)
        if before[:2] != expected:
            raise _RBACConflictError(
                "membership state changed before apply for "
                f"{group.id}/{user.id}: "
                f"expected member={_rbac_badge(expected[0])}, "
                f"approved={_rbac_badge(expected[1])}; "
                f"current member={_rbac_badge(before[0])}, "
                f"approved={_rbac_badge(before[1])}"
            )
    if bool(validated.get("has_expected_email_status")):
        expected_email_status = _rbac_email_status(
            str(validated.get("expected_email_status", audit_logic.EMAIL_STATUS_NONE))
        )
        if before[2] != expected_email_status:
            raise _RBACConflictError(
                "membership state changed before apply for "
                f"{group.id}/{user.id}: "
                f"expected email_status={expected_email_status}, "
                f"current email_status={before[2]}"
            )

    resend_attempted = False
    resend_result = ""
    after = (member, approved if member else False, audit_logic.EMAIL_STATUS_NONE)
    if member:
        row = existing
        if row is None:
            row = model.GroupMember(user=user.id, group=group.id)
        if approved:
            if row.approved is None:
                row.approved = func.now()
            row.email_status = audit_logic.EMAIL_STATUS_NONE
        else:
            row.approved = None
            if (
                set_email_status
                and requested_email_status == audit_logic.EMAIL_STATUS_SENT
            ):
                resend_attempted = True
                resend_result = notification_logic.notify_group_pi_of_join_form(
                    user,
                    group.id,
                )
                row.email_status = resend_result
            else:
                row.email_status = requested_email_status
        model.db.session.add(row)
        after = (
            True,
            bool(row.approved is not None),
            _rbac_email_status(row.email_status),
        )
    elif existing is not None:
        model.db.session.delete(existing)

    if before == after and not resend_attempted:
        return (
            f"Membership for {user.id} in {group.id} already matches requested state.",
            False,
        )

    _record_rbac_action(
        action="group.membership.set",
        where=f"/rbac?scope=group&entity={group.id}",
        how="rbac-explorer-batch",
        what=(
            f"group={group.id}, user={user.id}, "
            f"member={_rbac_badge(member)}, "
            f"approved={_rbac_badge(approved)}, "
            f"email_status={before[2]}->{after[2]}"
        ),
        source_ip=source_ip,
    )
    if (
        before[2] == audit_logic.EMAIL_STATUS_FAILED
        and after[2] != audit_logic.EMAIL_STATUS_FAILED
    ):
        audit_logic.log_email_issue_resolution(
            issue_key=f"join-group:{group.id}:{user.id}",
            actor=g.user.id if g.user is not None else "unknown",
            where=f"/rbac?scope=group&entity={group.id}",
            how="rbac-explorer-batch",
            details=(
                f"group={group.id}, requester={user.id}, "
                f"email_status={before[2]}->{after[2]}"
            ),
            source_ip=source_ip,
        )
    pending_before = bool(before[0] and not before[1])
    approved_after = bool(after[0] and after[1])
    denied_after = bool(not after[0])
    if pending_before and (approved_after or denied_after):
        notification_logic.notify_user_of_join_request_outcome(
            approved_after,
            user,
            group.label or group.id,
        )
    if resend_attempted:
        if resend_result == audit_logic.EMAIL_STATUS_SENT:
            return (
                f"Updated membership for {user.id} in {group.id} and resent request email.",
                True,
            )
        return (
            f"Updated membership for {user.id} in {group.id}; resend email failed.",
            True,
        )
    return (f"Updated membership for {user.id} in {group.id}.", True)


def _rbac_apply_group_pi_set(
    validated: Dict[str, Any], *, source_ip: str
) -> Tuple[str, bool]:
    group = validated["group"]
    user = validated["user"]
    current_pi_statement = (
        select(model.Membership)
        .where(model.Membership.group == group.id)
        .where(model.Membership.pi)
    )
    current_pi = model.db.session.scalars(current_pi_statement).first()
    current_pi_user = current_pi.user if current_pi is not None else ""

    expected_current_pi = str(validated.get("expected_current_pi", "")).strip()
    if (
        bool(validated.get("has_expected_current_pi"))
        and expected_current_pi != current_pi_user
    ):
        raise _RBACConflictError(
            "PI assignment changed before apply for "
            f"{group.id}: expected {expected_current_pi or 'none'}, "
            f"current {current_pi_user or 'none'}"
        )

    approved_members = {
        row.user
        for row in model.db.session.scalars(
            select(model.Membership)
            .where(model.Membership.group == group.id)
            .where(model.Membership.approved)
            .where(model.Membership.user_active)
            .where(model.Membership.group_active)
        ).all()
    }
    if user.id not in approved_members:
        raise ValueError(
            f"PI must be an approved active member of {group.id}: {user.id}"
        )

    if user.id == current_pi_user:
        return (f"PI for {group.id} already matches requested state.", False)
    core_logic.change_pi_of_group(group, user)
    _record_rbac_action(
        action="group.pi.update",
        where=f"/rbac?scope=group&entity={group.id}",
        how="rbac-explorer-batch",
        what=f"group={group.id}, from={current_pi_user or 'none'}, to={user.id}",
        source_ip=source_ip,
    )
    return (f"Updated PI for {group.id} to {user.id}.", True)


RELATIONSHIP_APPLIERS = {
    "device.group.set": _rbac_apply_device_group_set,
    "user.device.set": _rbac_apply_user_device_set,
    "group.membership.set": _rbac_apply_group_membership_set,
    "group.pi.set": _rbac_apply_group_pi_set,
}
