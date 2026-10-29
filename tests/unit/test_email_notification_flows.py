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

import scheduler.message as scheduler_message
from scheduler import logic, model


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Set MAILPIT__PORT or MAILPIT_API_BASE_URL for Mailpit-backed tests."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API is not reachable at {cfg.api_base_url}.")
    return cfg


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

            audit_row = (
                model.EmailAuditLog.query.filter(
                    model.EmailAuditLog.action == "email.join.outcome"
                )
                .filter(model.EmailAuditLog.recipient == addr)
                .order_by(model.EmailAuditLog.id.desc())
                .first()
            )
            assert audit_row is not None
            assert audit_row.status == logic.EMAIL_AUDIT_STATUS_SENT
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

            audit_row = (
                model.EmailAuditLog.query.filter(
                    model.EmailAuditLog.action == "email.join.tech.outcome"
                )
                .filter(model.EmailAuditLog.recipient == addr)
                .order_by(model.EmailAuditLog.id.desc())
                .first()
            )
            assert audit_row is not None
            assert audit_row.status == logic.EMAIL_AUDIT_STATUS_SENT
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
            assert all(note["msg"] == "success" for note in notes)
            model.db.session.flush()
            _wait_for_mail_count(cfg, expected=4)

            audit_rows = (
                model.EmailAuditLog.query.filter(
                    model.EmailAuditLog.action == "email.scheduler.notification"
                )
                .filter(model.EmailAuditLog.details.like(f"%device={device_id}%"))
                .all()
            )
            assert len(audit_rows) == 4
            assert all(
                row.status == logic.EMAIL_AUDIT_STATUS_SENT for row in audit_rows
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
    assert all(note["msg"] == "address" for note in notes)
    audit_rows = model.EmailAuditLog.query.filter(
        model.EmailAuditLog.action == "email.scheduler.notification"
    ).all()
    assert audit_rows == []
