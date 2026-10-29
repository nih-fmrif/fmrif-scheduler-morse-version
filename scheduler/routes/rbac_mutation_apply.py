from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from flask import g, request
from sqlalchemy import select
from sqlalchemy.sql import func

from scheduler import logic, model

from .rbac_mutation_validation import (
    _rbac_audit_preview,
    _rbac_email_status,
    _rbac_permission_flags,
    _RBACConflictError,
)


def _request_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    remote = (request.remote_addr or "").strip()
    return remote or "unknown"


def _record_rbac_action(
    action: str,
    where: str,
    how: str,
    what: str,
    *,
    source_ip: Optional[str] = None,
) -> None:
    actor = g.user.id if g.user is not None else "unknown"
    client_ip = source_ip or _request_client_ip()
    try:
        logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
            source_ip=client_ip,
        )
    except TypeError:
        logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
        )


def _rbac_actor_managed_groups(actor: Dict[str, Any]) -> Set[str]:
    groups = actor.get("managed_groups", set())
    if isinstance(groups, set):
        return groups
    return set()


def _rbac_badge(value: bool) -> str:
    return "yes" if value else "no"


def _rbac_state(value: bool) -> str:
    return "active" if value else "inactive"


def _rbac_apply_batch_operation(
    validated: Dict[str, Any],
    *,
    source_ip: str,
) -> Tuple[str, bool]:
    kind = str(validated["kind"])

    # Entity creation.
    if kind == "group.create":
        group_id = validated["group_id"]
        pi_user = validated["pi_user"]
        group = model.Group(
            id=group_id,
            label=validated["label"],
            description=validated["description"],
            color=validated["color"],
            addr=validated["addr"],
            link=validated["link"],
            active=bool(validated["active"]),
            inst=validated["inst"] or None,
        )
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

    if kind == "device.create":
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

    # Entity active-state toggles.
    if kind == "group.active.set":
        group = validated["group"]
        active = bool(validated["active"])
        current_active = bool(group.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "group active-state changed before apply for "
                    f"{group.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{group.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        group.active = active
        model.db.session.add(group)
        _record_rbac_action(
            action="group.update",
            where=f"/rbac?scope=group&entity={group.id}",
            how="rbac-explorer-batch",
            what=(
                f"group={group.id}, "
                f"active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {group.id} to {_rbac_state(active)}.", True)

    if kind == "device.active.set":
        device = validated["device"]
        active = bool(validated["active"])
        current_active = bool(device.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "device active-state changed before apply for "
                    f"{device.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{device.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        device.active = active
        model.db.session.add(device)
        _record_rbac_action(
            action="device.update",
            where=f"/rbac?scope=device&entity={device.id}",
            how="rbac-explorer-batch",
            what=(
                f"device={device.id}, "
                f"active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {device.id} to {_rbac_state(active)}.", True)

    if kind == "user.active.set":
        user = validated["user"]
        active = bool(validated["active"])
        current_active = bool(user.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "user active-state changed before apply for "
                    f"{user.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{user.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        user.active = active
        model.db.session.add(user)
        _record_rbac_action(
            action="user.update",
            where=f"/rbac?scope=user&entity={user.id}",
            how="rbac-explorer-batch",
            what=(
                f"user={user.id}, active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {user.id} to {_rbac_state(active)}.", True)

    # User profile and technologist request state.
    if kind == "user.profile.set":
        user = validated["user"]
        if bool(validated.get("has_expected_addr")):
            expected_addr = str(validated.get("expected_addr", ""))
            current_addr = user.addr or ""
            if current_addr != expected_addr:
                raise _RBACConflictError(
                    "user profile changed before apply for "
                    f"{user.id} field addr: "
                    f"expected {_rbac_audit_preview(expected_addr)}, "
                    f"current {_rbac_audit_preview(current_addr)}"
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

    if kind == "user.technologist.set":
        user = validated["user"]
        applied = bool(validated.get("applied"))
        approved = bool(validated.get("approved"))
        requested_email_status = _rbac_email_status(
            str(validated.get("email_status", logic.EMAIL_STATUS_NONE))
        )
        set_email_status = bool(validated.get("set_email_status"))
        existing = model.get(model.Technologist, user.id)
        before_applied = existing is not None
        before_approved = (
            bool(existing.approved_on is not None) if existing is not None else False
        )
        before_email_status = _rbac_email_status(
            existing.email_status if existing is not None else logic.EMAIL_STATUS_NONE
        )
        if bool(validated.get("has_expected_state")):
            expected_applied = bool(validated.get("expected_applied"))
            expected_approved = bool(validated.get("expected_approved"))
            if (
                before_applied != expected_applied
                or before_approved != expected_approved
            ):
                raise _RBACConflictError(
                    "technologist state changed before apply for "
                    f"{user.id}: expected applied={_rbac_badge(expected_applied)}, "
                    f"approved={_rbac_badge(expected_approved)}; "
                    f"current applied={_rbac_badge(before_applied)}, "
                    f"approved={_rbac_badge(before_approved)}"
                )
        if bool(validated.get("has_expected_email_status")):
            expected_email_status = _rbac_email_status(
                str(validated.get("expected_email_status", logic.EMAIL_STATUS_NONE))
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
                row.email_status = logic.EMAIL_STATUS_NONE
            else:
                row.approved_on = None
                if (
                    set_email_status
                    and requested_email_status == logic.EMAIL_STATUS_SENT
                ):
                    resend_attempted = True
                    resend_result = logic.notify_dev_pi_of_tech_join_form(user)
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
            after_email_status = logic.EMAIL_STATUS_NONE

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
            before_email_status == logic.EMAIL_STATUS_FAILED
            and after_email_status != logic.EMAIL_STATUS_FAILED
        ):
            logic.log_email_issue_resolution(
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
            if resend_result == logic.EMAIL_STATUS_SENT:
                return (
                    f"Updated technologist state for {user.id} and resent request email.",
                    True,
                )
            return (
                f"Updated technologist state for {user.id}; resend email failed.",
                True,
            )
        return (f"Updated technologist state for {user.id}.", True)

    # Group and device metadata edits.
    if kind == "group.meta.set":
        group = validated["group"]
        if bool(validated.get("has_expected_label")):
            expected_label = str(validated.get("expected_label", ""))
            current_label = group.label or ""
            if current_label != expected_label:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field label: "
                    f"expected {_rbac_audit_preview(expected_label)}, "
                    f"current {_rbac_audit_preview(current_label)}"
                )
        if bool(validated.get("has_expected_description")):
            expected_description = str(validated.get("expected_description", ""))
            current_description = group.description or ""
            if current_description != expected_description:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field description: "
                    f"expected {_rbac_audit_preview(expected_description)}, "
                    f"current {_rbac_audit_preview(current_description)}"
                )
        if bool(validated.get("has_expected_addr")):
            expected_addr = str(validated.get("expected_addr", ""))
            current_addr = group.addr or ""
            if current_addr != expected_addr:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field addr: "
                    f"expected {_rbac_audit_preview(expected_addr)}, "
                    f"current {_rbac_audit_preview(current_addr)}"
                )
        if bool(validated.get("has_expected_link")):
            expected_link = str(validated.get("expected_link", ""))
            current_link = group.link or ""
            if current_link != expected_link:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field link: "
                    f"expected {_rbac_audit_preview(expected_link)}, "
                    f"current {_rbac_audit_preview(current_link)}"
                )
        if bool(validated.get("has_expected_color")):
            expected_color = str(validated.get("expected_color", ""))
            current_color = group.color or ""
            if current_color != expected_color:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field color: "
                    f"expected {_rbac_audit_preview(expected_color)}, "
                    f"current {_rbac_audit_preview(current_color)}"
                )
        if bool(validated.get("has_expected_inst")):
            expected_inst = str(validated.get("expected_inst", ""))
            current_inst = group.inst or ""
            if current_inst != expected_inst:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field inst: "
                    f"expected {_rbac_audit_preview(expected_inst)}, "
                    f"current {_rbac_audit_preview(current_inst)}"
                )
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            current_active = bool(group.active)
            if current_active != expected_active:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field active: "
                    f"expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )

        changes: List[str] = []
        if bool(validated.get("set_label")):
            label = validated["label"]
            if group.label != label:
                changes.append(
                    f"label={_rbac_audit_preview(group.label)}->{_rbac_audit_preview(label)}"
                )
                group.label = label
        if bool(validated.get("set_description")):
            description = validated["description"]
            if group.description != description:
                changes.append(
                    "description="
                    f"{_rbac_audit_preview(group.description)}->"
                    f"{_rbac_audit_preview(description)}"
                )
                group.description = description
        if bool(validated.get("set_addr")):
            addr = validated["addr"]
            if group.addr != addr:
                changes.append(
                    f"addr={_rbac_audit_preview(group.addr)}->{_rbac_audit_preview(addr)}"
                )
                group.addr = addr
        if bool(validated.get("set_link")):
            link = validated["link"]
            if group.link != link:
                changes.append(
                    f"link={_rbac_audit_preview(group.link)}->{_rbac_audit_preview(link)}"
                )
                group.link = link
        if bool(validated.get("set_color")):
            color = validated["color"]
            if group.color != color:
                changes.append(
                    f"color={_rbac_audit_preview(group.color)}->{_rbac_audit_preview(color)}"
                )
                group.color = color
        if bool(validated.get("set_inst")):
            inst = validated["inst"]
            next_inst = inst or None
            if group.inst != next_inst:
                changes.append(
                    f"inst={_rbac_audit_preview(group.inst)}->{_rbac_audit_preview(next_inst)}"
                )
                group.inst = next_inst
        if bool(validated.get("set_active")):
            active = bool(validated["active"])
            if group.active != active:
                changes.append(
                    f"active={_rbac_badge(bool(group.active))}->{_rbac_badge(active)}"
                )
                group.active = active

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

    if kind == "device.meta.set":
        device = validated["device"]
        if bool(validated.get("has_expected_label")):
            expected_label = str(validated.get("expected_label", ""))
            current_label = device.label or ""
            if current_label != expected_label:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field label: "
                    f"expected {_rbac_audit_preview(expected_label)}, "
                    f"current {_rbac_audit_preview(current_label)}"
                )
        if bool(validated.get("has_expected_description")):
            expected_description = str(validated.get("expected_description", ""))
            current_description = device.description or ""
            if current_description != expected_description:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field description: "
                    f"expected {_rbac_audit_preview(expected_description)}, "
                    f"current {_rbac_audit_preview(current_description)}"
                )
        if bool(validated.get("has_expected_addr")):
            expected_addr = str(validated.get("expected_addr", ""))
            current_addr = device.addr or ""
            if current_addr != expected_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field addr: "
                    f"expected {_rbac_audit_preview(expected_addr)}, "
                    f"current {_rbac_audit_preview(current_addr)}"
                )
        if bool(validated.get("has_expected_tech_addr")):
            expected_tech_addr = str(validated.get("expected_tech_addr", ""))
            current_tech_addr = device.tech_addr or ""
            if current_tech_addr != expected_tech_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field tech_addr: "
                    f"expected {_rbac_audit_preview(expected_tech_addr)}, "
                    f"current {_rbac_audit_preview(current_tech_addr)}"
                )
        if bool(validated.get("has_expected_med_addr")):
            expected_med_addr = str(validated.get("expected_med_addr", ""))
            current_med_addr = device.med_addr or ""
            if current_med_addr != expected_med_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field med_addr: "
                    f"expected {_rbac_audit_preview(expected_med_addr)}, "
                    f"current {_rbac_audit_preview(current_med_addr)}"
                )
        if bool(validated.get("has_expected_train_addr")):
            expected_train_addr = str(validated.get("expected_train_addr", ""))
            current_train_addr = device.train_addr or ""
            if current_train_addr != expected_train_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field train_addr: "
                    f"expected {_rbac_audit_preview(expected_train_addr)}, "
                    f"current {_rbac_audit_preview(current_train_addr)}"
                )
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            current_active = bool(device.active)
            if current_active != expected_active:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field active: "
                    f"expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )

        changes: List[str] = []
        if bool(validated.get("set_label")):
            label = validated["label"]
            if device.label != label:
                changes.append(
                    f"label={_rbac_audit_preview(device.label)}->{_rbac_audit_preview(label)}"
                )
                device.label = label
        if bool(validated.get("set_description")):
            description = validated["description"]
            if device.description != description:
                changes.append(
                    "description="
                    f"{_rbac_audit_preview(device.description)}->"
                    f"{_rbac_audit_preview(description)}"
                )
                device.description = description
        if bool(validated.get("set_addr")):
            addr = validated["addr"]
            if device.addr != addr:
                changes.append(
                    f"addr={_rbac_audit_preview(device.addr)}->{_rbac_audit_preview(addr)}"
                )
                device.addr = addr
        if bool(validated.get("set_tech_addr")):
            tech_addr = validated["tech_addr"]
            if device.tech_addr != tech_addr:
                changes.append(
                    "tech_addr="
                    f"{_rbac_audit_preview(device.tech_addr)}->"
                    f"{_rbac_audit_preview(tech_addr)}"
                )
                device.tech_addr = tech_addr
        if bool(validated.get("set_med_addr")):
            med_addr = validated["med_addr"]
            if device.med_addr != med_addr:
                changes.append(
                    "med_addr="
                    f"{_rbac_audit_preview(device.med_addr)}->"
                    f"{_rbac_audit_preview(med_addr)}"
                )
                device.med_addr = med_addr
        if bool(validated.get("set_train_addr")):
            train_addr = validated["train_addr"]
            if device.train_addr != train_addr:
                changes.append(
                    "train_addr="
                    f"{_rbac_audit_preview(device.train_addr)}->"
                    f"{_rbac_audit_preview(train_addr)}"
                )
                device.train_addr = train_addr
        if bool(validated.get("set_active")):
            active = bool(validated["active"])
            if device.active != active:
                changes.append(
                    f"active={_rbac_badge(bool(device.active))}->{_rbac_badge(active)}"
                )
                device.active = active

        if len(changes) == 0:
            return (
                f"Metadata for {device.id} already matches requested state.",
                False,
            )

        model.db.session.add(device)
        _record_rbac_action(
            action="device.update",
            where=f"/rbac?scope=device&entity={device.id}",
            how="rbac-explorer-batch",
            what=f"device={device.id}, {'; '.join(changes)}",
            source_ip=source_ip,
        )
        return (f"Updated metadata for {device.id}.", True)

    # Relationship and permission links.
    if kind == "device.group.set":
        group = validated["group"]
        device = validated["device"]
        linked = bool(validated["linked"])
        existing = model.get(model.DeviceGroup, (device.id, group.id))
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

    if kind == "user.device.set":
        user = validated["user"]
        device = validated["device"]
        templates = bool(validated["templates"])
        slot = bool(validated["slot"])
        tech = bool(validated["tech"]) and bool(validated["is_technologist"])
        medical = bool(validated["medical"])
        training = bool(validated["training"])
        has_any_permission = bool(validated["has_any_permission"])
        existing = model.get(model.UserDevice, (user.id, device.id))
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
            return (
                f"{user.id} has no device-specific permissions on {device.id}.",
                False,
            )
        model.db.session.delete(existing)
        _record_rbac_action(
            action="user.device.remove",
            where=f"/rbac?scope=user&entity={user.id}",
            how="rbac-explorer-batch",
            what=f"device={device.id}, user={user.id}",
            source_ip=source_ip,
        )
        return (
            f"Removed device-specific permissions for {user.id} on {device.id}.",
            True,
        )

    # Group membership and PI assignment.
    if kind == "group.membership.set":
        group = validated["group"]
        user = validated["user"]
        member = bool(validated["member"])
        approved = bool(validated["approved"])
        requested_email_status = _rbac_email_status(
            str(validated.get("email_status", logic.EMAIL_STATUS_NONE))
        )
        set_email_status = bool(validated.get("set_email_status"))
        existing = model.get(model.GroupMember, (group.id, user.id))
        was_member = existing is not None
        was_approved = (
            bool(existing.approved is not None) if existing is not None else False
        )
        before_email_status = _rbac_email_status(
            existing.email_status if existing is not None else logic.EMAIL_STATUS_NONE
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
                str(validated.get("expected_email_status", logic.EMAIL_STATUS_NONE))
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
        after = (member, approved if member else False, logic.EMAIL_STATUS_NONE)
        if member:
            row = existing
            if row is None:
                row = model.GroupMember(user=user.id, group=group.id)
            if approved:
                if row.approved is None:
                    row.approved = func.now()
                row.email_status = logic.EMAIL_STATUS_NONE
            else:
                row.approved = None
                if (
                    set_email_status
                    and requested_email_status == logic.EMAIL_STATUS_SENT
                ):
                    resend_attempted = True
                    resend_result = logic.notify_group_pi_of_join_form(user, group.id)
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
            before[2] == logic.EMAIL_STATUS_FAILED
            and after[2] != logic.EMAIL_STATUS_FAILED
        ):
            logic.log_email_issue_resolution(
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
            logic.notify_user_of_join_request_outcome(
                approved_after,
                user,
                group.label or group.id,
            )
        if resend_attempted:
            if resend_result == logic.EMAIL_STATUS_SENT:
                return (
                    f"Updated membership for {user.id} in {group.id} and resent request email.",
                    True,
                )
            return (
                f"Updated membership for {user.id} in {group.id}; resend email failed.",
                True,
            )
        return (f"Updated membership for {user.id} in {group.id}.", True)

    if kind == "group.pi.set":
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
        if bool(validated.get("has_expected_current_pi")):
            if expected_current_pi != current_pi_user:
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
        if user.id != current_pi_user:
            logic.change_pi_of_group(group, user)
            _record_rbac_action(
                action="group.pi.update",
                where=f"/rbac?scope=group&entity={group.id}",
                how="rbac-explorer-batch",
                what=f"group={group.id}, from={current_pi_user or 'none'}, to={user.id}",
                source_ip=source_ip,
            )
            return (f"Updated PI for {group.id} to {user.id}.", True)
        return (f"PI for {group.id} already matches requested state.", False)

    raise ValueError(f"unsupported operation kind: {kind}")


def _rbac_authorize_batch_operation(
    validated: Dict[str, Any], actor: Dict[str, Any]
) -> None:
    if bool(actor.get("is_admin")):
        return

    kind = str(validated.get("kind", ""))
    managed_groups = _rbac_actor_managed_groups(actor)
    is_dev_pi = bool(actor.get("is_dev_pi"))

    if kind in {"group.meta.set", "group.membership.set", "group.pi.set"}:
        group = validated["group"]
        if group.id not in managed_groups:
            raise PermissionError(f"group not managed by current user: {group.id}")
        if not bool(group.active):
            raise PermissionError(f"inactive group requires admin access: {group.id}")
        if kind == "group.meta.set":
            if (validated.get("inst") or "") != (group.inst or ""):
                raise PermissionError("group institute edits require admin access")
            if bool(validated.get("active")) != bool(group.active):
                raise PermissionError("group active-state edits require admin access")
        return

    if kind in {"device.meta.set", "device.group.set", "user.device.set"}:
        if not is_dev_pi:
            raise PermissionError("device RBAC updates require DEV PI or admin access")
        device = validated["device"]
        if not bool(device.active):
            raise PermissionError(f"inactive device requires admin access: {device.id}")
        if kind == "device.meta.set" and bool(validated.get("active")) != bool(
            device.active
        ):
            raise PermissionError("device active-state edits require admin access")
        return

    raise PermissionError(f"operation requires admin access: {kind}")
