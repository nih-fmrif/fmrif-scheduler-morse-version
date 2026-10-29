"""Shared seed/setup helpers for route tests.

These helpers write to concrete tables (for example ``groupmembers`` and
``primarygroupmember``) so route tests remain compatible with SQL-bootstrap
schemas where ``membership`` is a read-only view.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Sequence

from scheduler import logic, model
from scheduler.app import app


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


def ensure_active_user(user_id: str, email: str, display_name: str) -> None:
    with app.app_context():
        user = logic.upsert_user(user_id, email, display_name)
        user.active = True
        model.db.session.add(user)
        model.db.session.commit()


def ensure_group(
    group_id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    color: str = "#123456",
    active: bool = True,
    has_membership: bool = True,
) -> None:
    with app.app_context():
        group = model.Group.query.get(group_id)
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
        model.db.session.commit()


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
    with app.app_context():
        model.db.session.add(
            model.Device(
                id=device_id,
                label=device_label,
                description=f"Description {suffix}",
                active=True,
            )
        )
        model.db.session.commit()
    return device_id, device_label


def seeded_scanner_id() -> str:
    """Return a scanner id guaranteed to exist in SQL-seeded route-test data."""
    with app.app_context():
        for scanner_id in ("TEST", "test"):
            scanner = model.Device.query.get(scanner_id)
            if scanner is not None and scanner.active:
                return scanner_id

        active = (
            model.Device.query.filter_by(active=True).order_by(model.Device.id).first()
        )
        if active is not None:
            return active.id

        for scanner_id in ("TEST", "test"):
            scanner = model.Device.query.get(scanner_id)
            if scanner is not None:
                return scanner_id

        any_device = model.Device.query.order_by(model.Device.id).first()
        if any_device is not None:
            return any_device.id

    raise AssertionError("No scanners exist in seeded route-test data")


def seeded_dev_user_id() -> str:
    """Return an existing approved DEV member id from seeded route-test data."""
    with app.app_context():
        row = model.db.session.execute(
            """
            select m."user"
            from membership m
            where m."group" = 'DEV'
              and m.approved
              and m.user_active
            order by m."user"
            limit 1
            """
        ).first()
        if row is not None:
            return row[0]

        user = model.User.query.filter_by(active=True).order_by(model.User.id).first()
        if user is not None:
            return user.id

    raise AssertionError("No active users exist in seeded route-test data")


def seeded_sched_log_id() -> str:
    """Return an existing schedule id for /json/v1/log/<id> contract checks."""
    with app.app_context():
        row = model.db.session.execute(
            """
            select s.schedid
            from tblsched s
            inner join tlkpscanner d on d.scannercode = s.scannercode
            where d.active
            order by s.schedid
            limit 1
            """
        ).first()
        if row is not None:
            return str(row[0])

        row = model.db.session.execute(
            "select s.schedid from tblsched s order by s.schedid limit 1"
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
    with app.app_context():
        membership = model.GroupMember.query.get((group_id, user_id))
        approved_at = datetime.now(timezone.utc) if approved else None
        if membership is None:
            membership = model.GroupMember(
                group=group_id,
                user=user_id,
                approved=approved_at,
            )
        else:
            membership.approved = approved_at
        model.db.session.add(membership)

        pi_entry = model.PrimaryGroupMember.query.get((group_id, user_id))
        if pi:
            current_pi = model.PrimaryGroupMember.query.filter_by(
                group=group_id
            ).first()
            if current_pi is not None and current_pi.user != user_id:
                # DB schema enforces one PI per group (deptcode uniqueness).
                # Use direct SQL delete so delete happens before insert in this txn.
                model.db.session.execute(
                    "delete from primarygroupmember where deptcode = :group_id",
                    {"group_id": group_id},
                )
                model.db.session.flush()
            if pi_entry is None:
                model.db.session.add(
                    model.PrimaryGroupMember(group=group_id, user=user_id)
                )
        elif pi_entry is not None:
            model.db.session.delete(pi_entry)
        model.db.session.commit()


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
