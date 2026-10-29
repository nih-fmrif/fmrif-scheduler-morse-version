# ruff: noqa: F401
import datetime
import json
import re
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from mailpit_api import (
    clear_mailpit_messages,
    get_mailpit_message,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    ensure_group,
    ensure_group_pi_user,
    extract_csrf_token,
    seeded_scanner_id,
    set_admin_session,
    set_group_membership,
    set_session_user,
)
from sqlalchemy import select

import scheduler.message as scheduler_message
from scheduler import logic, model
from scheduler.routes import rbac_routes

pytestmark = pytest.mark.route


def _latest_email_audit(*criteria):
    statement = select(model.EmailAuditLog).order_by(model.EmailAuditLog.id.desc())
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).first()


def _capture_rbac_events(
    monkeypatch,
) -> list[tuple[str, str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str, str]] = []

    def capture(
        action: str,
        actor: str,
        where: str,
        how: str,
        what: str,
        source_ip: str = "",
    ) -> None:
        events.append((action, actor, where, how, what, source_ip))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Mailpit API config missing. Set MAILPIT__PORT or MAILPIT_API_BASE_URL."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API not reachable at {cfg.api_base_url}.")
    return cfg


def _run_notification_scan(route_client, *, query: str = "") -> None:
    page = route_client.get(f"/app/issues{query}")
    assert page.status_code == 200
    csrf_token = extract_csrf_token(page.get_data(as_text=True))
    response = route_client.post(
        "/app/issues/notifications/scan",
        data={
            "csrf_token": csrf_token,
            "return_query": query.lstrip("?"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302


@contextmanager
def _route_mail_config(route_app, **mail_updates) -> Iterator[None]:
    original_mail_config = {
        "MAIL_SERVER": route_app.config.get("MAIL_SERVER"),
        "MAIL_PORT": route_app.config.get("MAIL_PORT"),
        "MAIL_USE_TLS": route_app.config.get("MAIL_USE_TLS"),
        "MAIL_USE_SSL": route_app.config.get("MAIL_USE_SSL"),
        "MAIL_SUPPRESS_SEND": route_app.config.get("MAIL_SUPPRESS_SEND"),
        "MAIL_DEFAULT_SENDER": route_app.config.get("MAIL_DEFAULT_SENDER"),
    }
    route_app.config.update(**mail_updates)
    scheduler_message.mailer.init_app(route_app)
    try:
        yield
    finally:
        route_app.config.update(**original_mail_config)
        scheduler_message.mailer.init_app(route_app)


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_updates_user_profile_email(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    user_id = f"profile-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@old.example.com", user_id)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "user.profile.set",
                        "user": user_id,
                        "addr": f"{user_id}@new.example.com",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 1
    row = model.get(model.User, user_id)
    assert row is not None
    assert row.addr == f"{user_id}@new.example.com"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_group_membership_sent_resends_notification(
    route_app, route_client, route_app_context
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    user_id = f"group-resend-{uuid.uuid4().hex[:6]}"
    pi_id = f"group-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    ensure_active_user(pi_id, f"{pi_id}@example.com", pi_id)
    set_group_membership(group_id, pi_id, approved=True, pi=True)
    model.db.session.add(
        model.GroupMember(
            group=group_id,
            user=user_id,
            approved=None,
            email_status="failed",
        )
    )
    model.db.session.flush()

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            csrf_token = extract_csrf_token(
                route_client.get("/rbac").get_data(as_text=True)
            )
            response = route_client.post(
                "/json/v1/rbac/mutate",
                data={
                    "csrf_token": csrf_token,
                    "mode": "batch",
                    "scope": "group",
                    "entity": group_id,
                    "operations": json.dumps(
                        [
                            {
                                "kind": "group.membership.set",
                                "group": group_id,
                                "user": user_id,
                                "member": True,
                                "approved": False,
                                "email_status": "sent",
                            }
                        ]
                    ),
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert payload["ok"] is True
            assert payload["applied"] == 1
            row = model.get(model.GroupMember, (group_id, user_id))
            assert row is not None
            assert row.email_status == "sent"
            resolution = _latest_email_audit(
                model.EmailAuditLog.action == "email.issue.resolved",
                model.EmailAuditLog.issue_key == f"join-group:{group_id}:{user_id}",
            )
            assert resolution is not None
            assert resolution.status == "resolved"

            subject = f"{user_id} has requested to join {group_id}"
            summary = wait_for_mailpit_message(
                cfg,
                lambda item: item.get("Subject") == subject,
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))
            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower() == f"{pi_id}@example.com"
                for recipient in recipients
                if isinstance(recipient, dict)
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.parametrize(
    ("member", "approved", "outcome"),
    [
        (True, True, "approved"),
        (False, False, "denied"),
    ],
)
@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_group_membership_outcome_notifies_requester(
    route_app,
    route_client,
    route_app_context,
    member,
    approved,
    outcome,
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"group-outcome-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, requester_id)
    ensure_group_pi_user(group_id, user_id=f"group-pi-{uuid.uuid4().hex[:6]}")
    model.db.session.add(
        model.GroupMember(
            group=group_id,
            user=requester_id,
            approved=None,
            email_status=logic.EMAIL_STATUS_NONE,
        )
    )
    model.db.session.flush()

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            csrf_token = extract_csrf_token(
                route_client.get("/rbac").get_data(as_text=True)
            )
            response = route_client.post(
                "/json/v1/rbac/mutate",
                data={
                    "csrf_token": csrf_token,
                    "mode": "batch",
                    "scope": "group",
                    "entity": group_id,
                    "operations": json.dumps(
                        [
                            {
                                "kind": "group.membership.set",
                                "group": group_id,
                                "user": requester_id,
                                "member": member,
                                "approved": approved,
                            }
                        ]
                    ),
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert payload["ok"] is True
            assert payload["applied"] == 1
            row = model.get(model.GroupMember, (group_id, requester_id))
            if approved:
                assert row is not None
                assert row.approved is not None
            else:
                assert row is None

            group = model.get(model.Group, group_id)
            group_name = group.label if group and group.label else group_id
            subject = f"your request to join {group_name} was {outcome}"
            summary = wait_for_mailpit_message(
                cfg,
                lambda item: item.get("Subject") == subject,
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))
            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower() == requester_email
                for recipient in recipients
                if isinstance(recipient, dict)
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_technologist_sent_resends_notification(
    route_app, route_client, route_app_context
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )

    user_id = f"tech-resend-{uuid.uuid4().hex[:6]}"
    dev_pi_id = f"dev-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    ensure_active_user(dev_pi_id, f"{dev_pi_id}@example.com", dev_pi_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    set_group_membership("DEV", dev_pi_id, approved=True, pi=True)
    model.db.session.add(
        model.Technologist(user=user_id, approved_on=None, email_status="failed")
    )
    model.db.session.flush()

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            csrf_token = extract_csrf_token(
                route_client.get("/rbac").get_data(as_text=True)
            )
            response = route_client.post(
                "/json/v1/rbac/mutate",
                data={
                    "csrf_token": csrf_token,
                    "mode": "batch",
                    "scope": "user",
                    "entity": user_id,
                    "operations": json.dumps(
                        [
                            {
                                "kind": "user.technologist.set",
                                "user": user_id,
                                "applied": True,
                                "approved": False,
                                "email_status": "sent",
                            }
                        ]
                    ),
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert payload["ok"] is True
            assert payload["applied"] == 1
            row = model.get(model.Technologist, user_id)
            assert row is not None
            assert row.approved_on is None
            assert row.email_status == "sent"
            resolution = _latest_email_audit(
                model.EmailAuditLog.action == "email.issue.resolved",
                model.EmailAuditLog.issue_key == f"join-tech:DEV:{user_id}",
            )
            assert resolution is not None
            assert resolution.status == "resolved"

            subject = f"{user_id} has requested technologist access"
            summary = wait_for_mailpit_message(
                cfg,
                lambda item: item.get("Subject") == subject,
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))
            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower() == f"{dev_pi_id}@example.com"
                for recipient in recipients
                if isinstance(recipient, dict)
            )
        finally:
            clear_mailpit_messages(cfg)
