"""Shared seed/setup helpers for route tests.

These helpers write to concrete tables (for example ``groupmembers`` and
``primarygroupmember``) so route tests remain compatible with SQL-bootstrap
schemas where ``membership`` is a read-only view.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Sequence

from flask import has_app_context
from sqlalchemy import delete, select, text

import scheduler.logic.core as logic
import scheduler.logic.rbac_audit_support as audit_logic
import scheduler.logic.templates as template_logic
from scheduler import model
from scheduler.app import create_app

_ROUTE_SEED_APP = None
_ROOTED_TEMPLATE_PREFERENCES: tuple[tuple[str, str], ...] = (
    ("d", "i"),
    ("d", "j"),
    ("d", "a"),
    ("test", "t"),
)


def _seed_app():
    global _ROUTE_SEED_APP
    if _ROUTE_SEED_APP is None:
        _ROUTE_SEED_APP = create_app()
    return _ROUTE_SEED_APP


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def set_session_user(
    client,
    *,
    username: str,
    email: str,
    display_name: str,
    groups: Sequence[str] | None = None,
) -> None:
    with client.session_transaction() as sess:
        sess["user_name"] = username
        sess["email"] = email
        sess["display_name"] = display_name
        sess["groups"] = list(groups or [])


def set_admin_session(client) -> None:
    set_session_user(
        client,
        username="test-admin",
        email="test-admin@example.com",
        display_name="Test Admin",
    )


@contextmanager
def _route_app_context():
    if has_app_context():
        yield False
        return

    with _seed_app().app_context():
        yield True


def _finalize_session_write(created_context: bool) -> None:
    # Keep writes visible in the current test transaction, but avoid extra commits
    # when an app context is already active for the test.
    if created_context:
        model.db.session.commit()
    else:
        model.db.session.flush()


def ensure_active_user(user_id: str, email: str, display_name: str) -> None:
    with _route_app_context() as created_context:
        user = logic.upsert_user(user_id, email, display_name)
        user.active = True
        model.db.session.add(user)
        _finalize_session_write(created_context)


def ensure_group(
    group_id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    color: str = "#123456",
    active: bool = True,
    has_membership: bool = True,
) -> None:
    with _route_app_context() as created_context:
        group = model.db.session.get(model.Group, group_id)
        if group is None:
            group = model.Group(id=group_id)

        group.label = label if label is not None else group_id
        group.description = (
            description if description is not None else f"Group {group_id}"
        )
        group.color = color
        group.active = active
        group.has_membership = has_membership
        model.db.session.add(group)
        _finalize_session_write(created_context)


def create_group(
    *,
    color: str = "#123456",
    has_membership: bool = True,
) -> str:
    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Description {group_id}",
        color=color,
        active=True,
        has_membership=has_membership,
    )
    return group_id


def create_device() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:4]
    device_id = f"D{suffix}"
    device_label = f"Device {suffix}"
    with _route_app_context() as created_context:
        model.db.session.add(
            model.Device(
                id=device_id,
                label=device_label,
                description=f"Description {suffix}",
                active=True,
            )
        )
        _finalize_session_write(created_context)
    return device_id, device_label


def seeded_scanner_id() -> str:
    """Return a scanner id guaranteed to exist in SQL-seeded route-test data."""
    with _route_app_context():
        for scanner_id in ("TEST", "test"):
            scanner = model.db.session.get(model.Device, scanner_id)
            if scanner is not None and scanner.active:
                return scanner_id

        active = (
            model.db.session.execute(
                select(model.Device)
                .where(model.Device.active.is_(True))
                .order_by(model.Device.id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if active is not None:
            return active.id

        for scanner_id in ("TEST", "test"):
            scanner = model.db.session.get(model.Device, scanner_id)
            if scanner is not None:
                return scanner_id

        any_device = (
            model.db.session.execute(
                select(model.Device).order_by(model.Device.id).limit(1)
            )
            .scalars()
            .first()
        )
        if any_device is not None:
            return any_device.id

    raise AssertionError("No scanners exist in seeded route-test data")


def _iter_seeded_template_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for device_id, template_id in _ROOTED_TEMPLATE_PREFERENCES:
        if model.db.session.get(model.Template, (template_id, device_id)) is None:
            continue
        keys.append((device_id, template_id))
        seen.add((device_id, template_id))

    for device_id, template_id in model.db.session.execute(
        text(
            """
        select scannercode, templatecode
        from tbltemplates
        order by scannercode, templatecode
        """
        )
    ):
        key = (str(device_id), str(template_id))
        if key in seen:
            continue
        keys.append(key)
        seen.add(key)

    return keys


def seeded_template_compatibility(
    *,
    archived: bool | None = None,
    require_blocking: bool | None = None,
    issue_code: str | None = None,
) -> tuple[str, str, dict[str, object]]:
    """Return a seeded template plus its current compatibility report."""

    with _route_app_context():
        for device_id, template_id in _iter_seeded_template_keys():
            template = model.db.session.get(model.Template, (template_id, device_id))
            if template is None:
                continue
            if archived is not None and template.hidden != archived:
                continue

            device = model.db.session.get(model.Device, device_id)
            if device is None:
                continue

            report = template_logic.inspect_template_compatibility(
                device, [template_id]
            ).get(template_id)
            if report is None:
                continue
            if (
                require_blocking is not None
                and bool(report["blocking"]) != require_blocking
            ):
                continue
            if issue_code is not None and not any(
                issue["code"] == issue_code for issue in report["issues"]
            ):
                continue
            return device_id, template_id, report

    filters = []
    if archived is not None:
        filters.append(f"archived={archived}")
    if require_blocking is not None:
        filters.append(f"blocking={require_blocking}")
    if issue_code is not None:
        filters.append(f"issue_code={issue_code}")
    details = ", ".join(filters) if filters else "no filters"
    raise AssertionError(
        f"No seeded template matched the rooted compatibility lookup ({details})"
    )


def seeded_dev_user_id() -> str:
    """Return an existing approved DEV member id from seeded route-test data."""
    with _route_app_context():
        row = model.db.session.execute(
            text(
                """
            select m."user"
            from membership m
            where m."group" = 'DEV'
              and m.approved
              and m.user_active
            order by m."user"
            limit 1
            """
            )
        ).first()
        if row is not None:
            return row[0]

        user = (
            model.db.session.execute(
                select(model.User)
                .where(model.User.active.is_(True))
                .order_by(model.User.id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if user is not None:
            return user.id

    raise AssertionError("No active users exist in seeded route-test data")


def seeded_group_scanner_id(group_id: str) -> str:
    """Return an active scanner linked to the requested group when possible."""
    with _route_app_context():
        scanner_id = model.db.session.execute(
            select(model.Device.id)
            .join(model.DeviceGroup, model.DeviceGroup.device == model.Device.id)
            .where(model.Device.active)
            .where(model.DeviceGroup.group == group_id)
            .order_by(model.Device.id)
            .limit(1)
        ).scalar()
        if scanner_id is not None:
            return str(scanner_id)

    return seeded_scanner_id()


def seeded_sched_log_id() -> str:
    """Return an existing schedule id for /json/v1/log/<id> contract checks."""
    with _route_app_context():
        row = model.db.session.execute(
            text(
                """
            select s.schedid
            from tblsched s
            inner join tlkpscanner d on d.scannercode = s.scannercode
            where d.active
            order by s.schedid
            limit 1
            """
            )
        ).first()
        if row is not None:
            return str(row[0])

        row = model.db.session.execute(
            text("select s.schedid from tblsched s order by s.schedid limit 1")
        ).first()
        if row is not None:
            return str(row[0])

    raise AssertionError("No schedule entries exist in seeded route-test data")


def set_group_membership(
    group_id: str,
    user_id: str,
    *,
    approved: bool = True,
    pi: bool = False,
) -> None:
    with _route_app_context() as created_context:
        membership = model.db.session.get(model.GroupMember, (group_id, user_id))
        approved_at = datetime.now(timezone.utc) if approved else None
        if membership is None:
            membership = model.GroupMember(
                group=group_id,
                user=user_id,
                approved=approved_at,
                email_status=audit_logic.EMAIL_STATUS_NONE,
            )
        else:
            membership.approved = approved_at
            if approved:
                membership.email_status = audit_logic.EMAIL_STATUS_NONE
        model.db.session.add(membership)

        pi_entry = model.db.session.get(model.PrimaryGroupMember, (group_id, user_id))
        if pi:
            current_pi = (
                model.db.session.execute(
                    select(model.PrimaryGroupMember)
                    .where(model.PrimaryGroupMember.group == group_id)
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if current_pi is not None and current_pi.user != user_id:
                # DB schema enforces one PI per group (deptcode uniqueness).
                # Use an explicit delete so it happens before insert in this txn.
                model.db.session.execute(
                    delete(model.PrimaryGroupMember).where(
                        model.PrimaryGroupMember.group == group_id
                    )
                )
                model.db.session.flush()
            if pi_entry is None:
                model.db.session.add(
                    model.PrimaryGroupMember(group=group_id, user=user_id)
                )
        elif pi_entry is not None:
            model.db.session.delete(pi_entry)
        _finalize_session_write(created_context)


def ensure_admin_user() -> None:
    ensure_group(
        "admin",
        label="admin",
        description="Admin",
        color="#111111",
        active=True,
        has_membership=True,
    )
    ensure_active_user("test-admin", "test-admin@example.com", "Test Admin")
    set_group_membership("admin", "test-admin", approved=True, pi=True)


def ensure_group_pi_user(
    group_id: str,
    *,
    user_id: str = "test-group-pi",
) -> tuple[str, str]:
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Test Group PI")
    set_group_membership(group_id, user_id, approved=True, pi=True)
    return user_id, email


def ensure_dev_pi_user(*, user_id: str = "test-dev-pi") -> tuple[str, str]:
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Test DEV PI")
    set_group_membership("DEV", user_id, approved=True, pi=True)
    return user_id, email
