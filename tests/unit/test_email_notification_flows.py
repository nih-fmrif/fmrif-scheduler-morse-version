import datetime
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from mailpit_api import (
    clear_mailpit_messages,
    list_mailpit_messages,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)
from sqlalchemy import select

import scheduler.logic.notifications as logic
import scheduler.logic.rbac_audit_support as audit_logic
import scheduler.logic.schedule_editor as schedule_logic
import scheduler.message as scheduler_message
from scheduler import model
from scheduler.logic.admin_issues import scheduler_notification_issue_key

pytestmark = pytest.mark.xdist_group("mailpit")


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Set MAILPIT__PORT or MAILPIT_API_BASE_URL for Mailpit-backed tests."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API is not reachable at {cfg.api_base_url}.")
    return cfg


def _email_audit_rows(*criteria):
    statement = select(model.EmailAuditLog)
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).all()


def _notification_incident(issue_key: str) -> model.NotificationIncident | None:
    return model.db.session.get(model.NotificationIncident, issue_key)


def _latest_email_audit(*criteria):
    statement = select(model.EmailAuditLog).order_by(model.EmailAuditLog.id.desc())
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).first()


@contextmanager
def _app_mail_config(app, **mail_updates) -> Iterator[None]:
    original_mail_config = {
        "MAIL_SERVER": app.config.get("MAIL_SERVER"),
        "MAIL_PORT": app.config.get("MAIL_PORT"),
        "MAIL_USE_TLS": app.config.get("MAIL_USE_TLS"),
        "MAIL_USE_SSL": app.config.get("MAIL_USE_SSL"),
        "MAIL_SUPPRESS_SEND": app.config.get("MAIL_SUPPRESS_SEND"),
        "MAIL_DEFAULT_SENDER": app.config.get("MAIL_DEFAULT_SENDER"),
    }
    app.config.update(**mail_updates)
    scheduler_message.mailer.init_app(app)
    try:
        yield
    finally:
        app.config.update(**original_mail_config)
        scheduler_message.mailer.init_app(app)


def _wait_for_mail_count(cfg, *, expected: int, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if len(list_mailpit_messages(cfg)) >= expected:
            return
        time.sleep(0.2)
    raise AssertionError(
        f"Expected at least {expected} Mailpit messages within {timeout_seconds}s."
    )


def test_prepare_notifications_includes_future_schedule_and_support_changes():
    slot_date = datetime.date(2035, 2, 21)
    diffs = [
        {
            "id": 101,
            "date": slot_date.isoformat(),
            "hour": 8,
            "group": ["", "BEI"],
            "member": ["", "user0048"],
        }
    ]
    srs_notes = [
        {
            "id": 101,
            "kind": "medical",
            "state": "approved",
            "handler": "user0049",
        }
    ]
    when = {
        101: (False, slot_date, 8),
    }

    schedule_notes, support_notes = logic.prepare_notifications(
        True, when, diffs, srs_notes
    )

    assert schedule_notes == diffs
    assert support_notes["schedule"] == [(slot_date, 8, srs_notes[0])]
    assert support_notes["medical"] == [(slot_date, 8, srs_notes[0])]
    assert support_notes["training"] == []
    assert support_notes["technologist"] == []


def test_prepare_notifications_suppresses_all_scheduler_messages_when_notify_disabled():
    slot_date = datetime.date(2035, 2, 22)
    diffs = [
        {
            "id": 102,
            "date": slot_date.isoformat(),
            "hour": 8,
            "group": ["", "BEI"],
            "member": ["", "user0048"],
        }
    ]
    srs_notes = [
        {
            "id": 102,
            "kind": "medical",
            "state": "new",
        }
    ]
    when = {
        102: (False, slot_date, 8),
    }

    schedule_notes, support_notes = logic.prepare_notifications(
        False, when, diffs, srs_notes
    )

    assert schedule_notes == []
    assert support_notes == {
        "schedule": [],
        "training": [],
        "medical": [],
        "technologist": [],
    }


@pytest.mark.parametrize(
    ("state", "handler", "subkind", "expected_lines"),
    [
        ("new", None, None, ("new request",)),
        ("updated", None, None, ("request updated",)),
        ("retracted", None, None, ("request retracted",)),
        ("denied", None, None, ("request denied",)),
        ("canceled", None, None, ("request canceled",)),
        (
            "unassigned",
            None,
            None,
            ("request no longer has handler but still open",),
        ),
        (
            "reassigned",
            "user0049",
            None,
            ("request reassigned to new handler", "to be handled by user0049"),
        ),
        (
            "approved",
            "user0049",
            None,
            ("request approved", "to be handled by user0049"),
        ),
        (
            "approved",
            "user0049",
            ("cover", "scan"),
            (
                "request approved",
                "to be handled by user0049",
                "scan/cover set to scan",
            ),
        ),
    ],
)
def test_fmt_support_notifications_covers_scheduler_support_states(
    state, handler, subkind, expected_lines
):
    hours = schedule_logic.fmt_hours()
    note = {
        "id": 103,
        "kind": "medical",
        "state": state,
    }
    if handler is not None:
        note["handler"] = handler
    if subkind is not None:
        note["subkind"] = subkind

    text = logic.fmt_support_notifications(
        hours,
        [(datetime.date(2035, 2, 23), 8, note)],
        False,
    )

    assert "2035-02-23: 8am" in text
    for expected_line in expected_lines:
        assert expected_line in text


def test_fmt_notifications_routes_support_changes_to_schedule_and_kind_streams():
    support_note = {
        "id": 104,
        "kind": "technologist",
        "state": "approved",
        "handler": "user0049",
        "subkind": ("cover", "scan"),
    }
    notifications = logic.fmt_notifications(
        [
            {
                "id": 104,
                "date": "2035-02-24",
                "hour": 8,
                "group": ["", "BEI"],
                "member": ["", "user0048"],
            }
        ],
        {
            "schedule": [(datetime.date(2035, 2, 24), 8, support_note)],
            "training": [],
            "medical": [],
            "technologist": [(datetime.date(2035, 2, 24), 8, support_note)],
        },
    )

    assert "2035-02-24: 8am" in notifications["schedule"]
    assert "\tset group to BEI" in notifications["schedule"]
    assert "Support Requests" in notifications["schedule"]
    assert "\ttechnologist" in notifications["schedule"]
    assert "request approved" in notifications["schedule"]
    assert "to be handled by user0049" in notifications["schedule"]
    assert "scan/cover set to scan" in notifications["schedule"]
    assert notifications["training"] == ""
    assert notifications["medical"] == ""
    assert "request approved" in notifications["technologist"]
    assert "to be handled by user0049" in notifications["technologist"]
    assert "scan/cover set to scan" in notifications["technologist"]


def test_notify_user_of_join_request_outcome_delivers_mail_and_audits(app_context):
    cfg = _require_mailpit()
    user_id = f"join-outcome-{uuid.uuid4().hex[:6]}"
    addr = f"{user_id}@example.com"
    user = model.User(id=user_id, label="Join Outcome User", active=True, addr=addr)
    model.db.session.add(user)
    model.db.session.flush()

    with _app_mail_config(
        app_context,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            logic.notify_user_of_join_request_outcome(True, user, "DEV")
            model.db.session.flush()

            audit_row = _latest_email_audit(
                model.EmailAuditLog.action == "email.join.outcome",
                model.EmailAuditLog.recipient == addr,
            )
            assert audit_row is not None
            assert audit_row.status == audit_logic.EMAIL_AUDIT_STATUS_SENT
            assert "approved" in audit_row.subject

            summary = wait_for_mailpit_message(
                cfg,
                lambda row: row.get("Subject")
                == "your request to join DEV was approved",
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
        finally:
            clear_mailpit_messages(cfg)


def test_notify_user_of_tech_join_request_outcome_delivers_mail_and_audits(app_context):
    cfg = _require_mailpit()
    user_id = f"tech-outcome-{uuid.uuid4().hex[:6]}"
    addr = f"{user_id}@example.com"
    user = model.User(id=user_id, label="Tech Outcome User", active=True, addr=addr)
    model.db.session.add(user)
    model.db.session.flush()

    with _app_mail_config(
        app_context,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            logic.notify_user_of_tech_join_request_outcome(False, user)
            model.db.session.flush()

            audit_row = _latest_email_audit(
                model.EmailAuditLog.action == "email.join.tech.outcome",
                model.EmailAuditLog.recipient == addr,
            )
            assert audit_row is not None
            assert audit_row.status == audit_logic.EMAIL_AUDIT_STATUS_SENT
            assert "denied" in audit_row.subject

            summary = wait_for_mailpit_message(
                cfg,
                lambda row: row.get("Subject")
                == "your request for technologist access was denied",
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
        finally:
            clear_mailpit_messages(cfg)


def test_send_scheduler_notifications_delivers_all_streams_and_audits(app_context):
    cfg = _require_mailpit()
    device_id = f"D{uuid.uuid4().hex[:4]}"
    device = model.Device(
        id=device_id,
        label=f"Device {device_id}",
        description="Scheduler mail test device",
        active=True,
        addr="schedule@example.com",
        train_addr="training@example.com",
        med_addr="medical@example.com",
        tech_addr="tech@example.com",
    )
    model.db.session.add(device)
    model.db.session.flush()

    messages = {
        "schedule": "schedule diff",
        "training": "training diff",
        "medical": "medical diff",
        "technologist": "technologist diff",
    }

    with _app_mail_config(
        app_context,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            notes = logic.send_scheduler_notifications(device, messages)
            assert len(notes) == 4
            assert all(note["status"] == "success" for note in notes)
            assert all("notification sent" in note["message"].lower() for note in notes)
            model.db.session.flush()
            _wait_for_mail_count(cfg, expected=4)

            audit_rows = _email_audit_rows(
                model.EmailAuditLog.action == "email.scheduler.notification",
                model.EmailAuditLog.details.like(f"%device={device_id}%"),
            )
            assert len(audit_rows) == 4
            assert all(
                row.status == audit_logic.EMAIL_AUDIT_STATUS_SENT for row in audit_rows
            )
        finally:
            clear_mailpit_messages(cfg)


def test_send_scheduler_notifications_records_missing_address_notes(app_context):
    device_id = f"D{uuid.uuid4().hex[:4]}"
    device = model.Device(
        id=device_id,
        label=f"Device {device_id}",
        description="Scheduler mail test device",
        active=True,
        addr="",
        train_addr="",
        med_addr="",
        tech_addr="",
    )
    model.db.session.add(device)
    model.db.session.flush()

    messages = {
        "schedule": "schedule diff",
        "training": "training diff",
        "medical": "medical diff",
        "technologist": "technologist diff",
    }

    notes = logic.send_scheduler_notifications(device, messages)
    assert len(notes) == 4
    assert all(note["status"] == "missing_recipient" for note in notes)
    assert all(
        "no recipient address is configured" in note["message"].lower()
        for note in notes
    )
    audit_rows = _email_audit_rows(
        model.EmailAuditLog.action == "email.scheduler.notification"
    )
    assert audit_rows == []
    for stream in ("schedule", "training", "medical", "technologist"):
        row = _notification_incident(
            scheduler_notification_issue_key(device_id, stream, "missing_recipient")
        )
        assert row is not None
        assert row.active is True
        assert row.state == "open"


def test_send_scheduler_notifications_marks_suppressed_delivery_as_skipped(
    app_context,
):
    device_id = f"D{uuid.uuid4().hex[:4]}"
    device = model.Device(
        id=device_id,
        label=f"Device {device_id}",
        description="Scheduler mail suppression test device",
        active=True,
        addr="schedule@example.com",
        train_addr="training@example.com",
        med_addr="medical@example.com",
        tech_addr="tech@example.com",
    )
    model.db.session.add(device)
    model.db.session.flush()

    messages = {
        "schedule": "schedule diff",
        "training": "training diff",
        "medical": "medical diff",
        "technologist": "technologist diff",
    }

    with _app_mail_config(app_context, MAIL_SUPPRESS_SEND=True):
        notes = logic.send_scheduler_notifications(device, messages)
        assert len(notes) == 4
        assert all(note["status"] == "skipped" for note in notes)
        model.db.session.flush()

        audit_rows = _email_audit_rows(
            model.EmailAuditLog.action == "email.scheduler.notification",
            model.EmailAuditLog.details.like(f"%device={device_id}%"),
        )
        assert len(audit_rows) == 4
        assert all(
            row.status == audit_logic.EMAIL_AUDIT_STATUS_SKIPPED for row in audit_rows
        )


def test_send_scheduler_notifications_resolves_live_missing_recipient_issue(
    app_context,
):
    device_id = f"D{uuid.uuid4().hex[:4]}"
    device = model.Device(
        id=device_id,
        label=f"Device {device_id}",
        description="Scheduler live issue resolution test device",
        active=True,
        addr="",
        train_addr="",
        med_addr="",
        tech_addr="",
    )
    model.db.session.add(device)
    model.db.session.flush()

    messages = {
        "schedule": "schedule diff",
        "training": "",
        "medical": "",
        "technologist": "",
    }

    notes = logic.send_scheduler_notifications(device, messages, actor="tester")
    assert notes[0]["status"] == "missing_recipient"
    model.db.session.commit()

    issue_key = scheduler_notification_issue_key(
        device_id, "schedule", "missing_recipient"
    )
    row = _notification_incident(issue_key)
    assert row is not None
    assert row.active is True
    assert row.state == "open"

    device.addr = "schedule@example.com"
    model.db.session.add(device)
    model.db.session.flush()

    cfg = _require_mailpit()
    with _app_mail_config(
        app_context,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            success_notes = logic.send_scheduler_notifications(
                device, messages, actor="tester"
            )
            assert success_notes[0]["status"] == "success"
            model.db.session.commit()
        finally:
            clear_mailpit_messages(cfg)

    row = _notification_incident(issue_key)
    assert row is not None
    assert row.active is False
    assert row.state == "resolved"


def test_prepare_notifications_returns_empty_when_notifications_are_disabled():
    when = {
        1: (False, "2035-04-21", 9),
        2: (False, "2035-04-21", 10),
    }
    diffs = [
        {"id": 1, "date": "2035-04-21", "hour": 9, "group": ["", "LFMI"]},
        {"id": 2, "date": "2035-04-21", "hour": 10, "member": ["", "user0033"]},
    ]
    srs_notes = [
        {"id": 1, "kind": "medical", "note": "coverage requested"},
    ]

    schedule_entries, support_entries = logic.prepare_notifications(
        False, when, diffs, srs_notes
    )

    assert schedule_entries == []
    assert support_entries == {
        "schedule": [],
        "training": [],
        "medical": [],
        "technologist": [],
    }
