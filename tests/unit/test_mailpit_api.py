import os
import smtplib
import uuid
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Iterator

import pytest
from mailpit_api import (
    clear_mailpit_messages,
    get_mailpit_message,
    list_mailpit_messages,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)


@contextmanager
def _env_override(
    *,
    set_values: dict[str, str] | None = None,
    unset_keys: list[str] | None = None,
) -> Iterator[None]:
    set_values = set_values or {}
    unset_keys = unset_keys or []
    touched_keys = set(set_values.keys()) | set(unset_keys)
    previous = {key: os.environ.get(key) for key in touched_keys}
    try:
        for key in unset_keys:
            os.environ.pop(key, None)
        for key, value in set_values.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _send_probe_email(cfg, *, subject: str) -> None:
    msg = EmailMessage()
    msg["From"] = "mailpit-probe@example.com"
    msg["To"] = "receiver@example.com"
    msg["Subject"] = subject
    msg.set_content("mailpit api probe")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=5) as client:
        client.send_message(msg)


def test_mailpit_config_from_env_uses_mailpit_ports_without_base_url():
    with _env_override(
        set_values={
            "MAILPIT__PORT": "5545",
            "MAILPIT__SMTP_PORT": "5546",
            "MAILPIT_SMTP_HOST": "localhost",
        },
        unset_keys=["MAILPIT_API_BASE_URL", "MAIL__PORT"],
    ):
        cfg = mailpit_config_from_env()
    assert cfg is not None
    assert cfg.api_base_url == "http://127.0.0.1:5545"
    assert cfg.smtp_host == "localhost"
    assert cfg.smtp_port == 5546


def test_mailpit_config_from_env_prefers_explicit_base_url():
    with _env_override(
        set_values={
            "MAILPIT_API_BASE_URL": "http://mailpit.local:8025/",
            "MAIL__PORT": "2025",
        },
        unset_keys=["MAILPIT__PORT", "MAILPIT__SMTP_PORT", "MAILPIT_SMTP_HOST"],
    ):
        cfg = mailpit_config_from_env()
    assert cfg is not None
    assert cfg.api_base_url == "http://mailpit.local:8025"
    assert cfg.smtp_host == "127.0.0.1"
    assert cfg.smtp_port == 2025


def test_mailpit_api_roundtrip_against_live_service():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip("Set MAILPIT__PORT or MAILPIT_API_BASE_URL for Mailpit tests.")
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API is not reachable at {cfg.api_base_url}.")

    subject = f"mailpit-api-{uuid.uuid4().hex[:8]}"
    clear_mailpit_messages(cfg)
    try:
        _send_probe_email(cfg, subject=subject)
        summary = wait_for_mailpit_message(
            cfg,
            lambda _row: True,
            timeout_seconds=8.0,
            poll_interval_seconds=0.2,
        )
        assert summary is not None

        messages = list_mailpit_messages(cfg)
        message_ids = {str(row.get("ID")) for row in messages}
        assert str(summary["ID"]) in message_ids

        detail = get_mailpit_message(cfg, str(summary["ID"]))
        sender = detail.get("From", {})
        assert isinstance(sender, dict)
        assert str(sender.get("Address", "")).lower() == "mailpit-probe@example.com"
        assert "mailpit api probe" in str(detail.get("Text", "")).lower()
    finally:
        clear_mailpit_messages(cfg)
    assert list_mailpit_messages(cfg) == []
