import socket
import uuid

import pytest
from flask import Flask
from mailpit_api import (
    clear_mailpit_messages,
    get_mailpit_message,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)

from scheduler import message


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _mail_app(**config_overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(
        MAIL_DEFAULT_SENDER="noreply@example.com",
        MAIL_SUPPRESS_SEND=False,
    )
    app.config.update(**config_overrides)
    message.mailer.init_app(app)
    return app


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Set MAILPIT__PORT or MAILPIT_API_BASE_URL for Mailpit-backed tests."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API is not reachable at {cfg.api_base_url}.")
    return cfg


def test_send_returns_false_when_smtp_endpoint_is_unreachable():
    closed_port = _unused_local_port()
    app = _mail_app(
        MAIL_SERVER="127.0.0.1",
        MAIL_PORT=closed_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
    )
    with app.app_context():
        assert message.send("to@example.com", "subject", "body") is False


def test_send_marks_suppressed_delivery_as_skipped(monkeypatch):
    app = _mail_app(
        MAIL_SUPPRESS_SEND=True,
        MAIL_SERVER="127.0.0.1",
        MAIL_PORT=_unused_local_port(),
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
    )
    captured = {}

    def fake_log_email_audit_event(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "scheduler.logic.log_email_audit_event", fake_log_email_audit_event
    )

    with app.app_context():
        assert message.send("to@example.com", "subject", "body") is True

    assert captured["status"] == "skipped"
    assert captured["recipient"] == "to@example.com"
    assert captured["subject"] == "subject"


def test_send_uses_mail_default_sender_and_splits_recipients():
    cfg = _require_mailpit()
    app = _mail_app(
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_DEFAULT_SENDER="noreply@example.com",
    )
    subject = f"message-default-sender-{uuid.uuid4().hex[:8]}"
    to_header = "first@example.com, second@example.com"

    clear_mailpit_messages(cfg)
    try:
        with app.app_context():
            assert message.send(to_header, subject, "hello from test") is True

        summary = wait_for_mailpit_message(
            cfg,
            lambda row: row.get("Subject") == subject,
            timeout_seconds=8.0,
            poll_interval_seconds=0.2,
        )
        assert summary is not None
        detail = get_mailpit_message(cfg, str(summary["ID"]))

        sender = detail.get("From", {})
        assert isinstance(sender, dict)
        assert str(sender.get("Address", "")).lower() == "noreply@example.com"

        recipients = detail.get("To", [])
        assert isinstance(recipients, list)
        recipient_addrs = {
            str(item.get("Address", "")).lower()
            for item in recipients
            if isinstance(item, dict)
        }
        assert recipient_addrs == {"first@example.com", "second@example.com"}
    finally:
        clear_mailpit_messages(cfg)


def test_send_uses_explicit_sender_override():
    cfg = _require_mailpit()
    app = _mail_app(
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_DEFAULT_SENDER="noreply@example.com",
    )
    sender = "requester@example.com"
    subject = f"message-explicit-sender-{uuid.uuid4().hex[:8]}"

    clear_mailpit_messages(cfg)
    try:
        with app.app_context():
            assert message.send(
                "listserv@example.com", subject, "payload", sender=sender
            )

        summary = wait_for_mailpit_message(
            cfg,
            lambda row: row.get("Subject") == subject,
            timeout_seconds=8.0,
            poll_interval_seconds=0.2,
        )
        assert summary is not None
        detail = get_mailpit_message(cfg, str(summary["ID"]))
        from_row = detail.get("From", {})
        assert isinstance(from_row, dict)
        assert str(from_row.get("Address", "")).lower() == sender
    finally:
        clear_mailpit_messages(cfg)
