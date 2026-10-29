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
    extract_csrf_token,
    seeded_scanner_id,
    set_admin_session,
    set_group_membership,
    set_session_user,
)

import scheduler.logic.core as core_logic
import scheduler.logic.rbac_audit_support as logic
import scheduler.message as scheduler_message
from scheduler import model
from scheduler.routes import rbac_routes

pytestmark = pytest.mark.route


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
def test_rbac_mutate_batch_admin_can_approve_pending_technologist_request(
    route_client, route_app_context
):
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

    user_id = f"tech-rbac-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    model.db.session.add(
        model.Technologist(user=user_id, approved_on=None, email_status="failed")
    )
    model.db.session.flush()

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
                        "kind": "user.technologist.set",
                        "user": user_id,
                        "applied": True,
                        "approved": True,
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
    row = model.db.session.get(model.Technologist, user_id)
    assert row is not None
    assert row.approved_on is not None


@pytest.mark.covers_route("/app/issues", "GET")
def test_app_issues_page_renders_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Admin Panel" in body
    assert "<title>Admin Panel - device scheduler</title>" in body
    assert "Potential issues" in body
    assert "RBAC audit log" not in body
    assert "Email audit log" in body


def test_app_issues_page_shows_missing_pi_issue(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        active=True,
        has_membership=True,
    )
    _run_notification_scan(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"Group {group_id} has no active PI configured" in body


def test_app_issues_page_defaults_audit_limits_to_10(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)

    captured: dict[str, int] = {}

    def fake_email_rows(scope: str, entity: str, *, limit: int, **_kwargs):
        captured["email"] = limit
        return []

    monkeypatch.setattr(logic, "rbac_audit_table_available", lambda: True)
    monkeypatch.setattr(logic, "email_audit_table_available", lambda: True)
    monkeypatch.setattr(logic, "notification_incident_table_available", lambda: False)
    monkeypatch.setattr(rbac_routes, "_email_audit_rows", fake_email_rows)
    monkeypatch.setattr(rbac_routes, "_build_potential_issues", lambda: [])
    monkeypatch.setattr(rbac_routes, "_build_potential_issue_sections", lambda _i: [])

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    assert captured == {"email": 10}


def test_app_issues_page_clamps_audit_limits_to_200(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)

    captured: dict[str, int] = {}

    def fake_email_rows(scope: str, entity: str, *, limit: int, **_kwargs):
        captured["email"] = limit
        return []

    monkeypatch.setattr(logic, "rbac_audit_table_available", lambda: True)
    monkeypatch.setattr(logic, "email_audit_table_available", lambda: True)
    monkeypatch.setattr(logic, "notification_incident_table_available", lambda: False)
    monkeypatch.setattr(rbac_routes, "_email_audit_rows", fake_email_rows)
    monkeypatch.setattr(rbac_routes, "_build_potential_issues", lambda: [])
    monkeypatch.setattr(rbac_routes, "_build_potential_issue_sections", lambda _i: [])

    response = route_client.get("/app/issues?limit=9999&email_limit=9999")
    assert response.status_code == 200
    assert captured == {"email": 200}


def test_build_potential_issues_batches_pi_user_resolution(
    monkeypatch, route_app_context
):
    from scheduler.routes.rbac_issues import _build_potential_issues

    group_id = create_group()
    pi_id = f"pib{uuid.uuid4().hex[:6]}"
    ensure_active_user(pi_id, f"{pi_id}@example.com", pi_id)
    set_group_membership(group_id, pi_id, approved=True, pi=True)

    original_get_user = core_logic.get_user
    call_count = 0

    def tracked_get_user(user_id: str):
        nonlocal call_count
        call_count += 1
        return original_get_user(user_id)

    monkeypatch.setattr(core_logic, "get_user", tracked_get_user)

    with route_app_context.test_request_context("/app/issues"):
        issues = _build_potential_issues()
    assert isinstance(issues, list)
    assert call_count == 0


def test_app_issues_page_surfaces_failed_join_request_notification(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"join-{uuid.uuid4().hex[:6]}"
    ensure_active_user(requester_id, f"{requester_id}@example.com", requester_id)
    model.db.session.add(
        model.GroupMember(
            group=group_id,
            user=requester_id,
            approved=None,
            email_status="failed",
        )
    )
    model.db.session.commit()
    _run_notification_scan(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Join request notification failed" in body
    assert requester_id in body
    assert group_id in body
    assert 'class="potential-issue-card urgent"' in body
    assert (
        re.search(
            r'<details[^>]*class="potential-issue-card urgent"[^>]*\bopen\b',
            body,
        )
        is None
    )


def test_app_issues_page_defaults_notification_state_filter_to_open(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert (
        re.search(
            r'id="notification-include-open"[^>]*checked',
            body,
        )
        is not None
    )
    assert (
        re.search(
            r'id="notification-include-ignored"[^>]*checked',
            body,
        )
        is None
    )
    assert (
        re.search(
            r'id="notification-include-resolved"[^>]*checked',
            body,
        )
        is None
    )


@pytest.mark.covers_route("/app/issues/notifications/scan", "POST")
def test_app_issues_scan_persists_detected_incidents(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"scan-{uuid.uuid4().hex[:6]}"
    ensure_active_user(requester_id, f"{requester_id}@example.com", requester_id)
    model.db.session.add(
        model.GroupMember(
            group=group_id,
            user=requester_id,
            approved=None,
            email_status="failed",
        )
    )
    model.db.session.commit()

    _run_notification_scan(route_client)

    issue_key = f"join-group:{group_id}:{requester_id}"
    row = model.db.session.get(model.NotificationIncident, issue_key)
    assert row is not None
    assert row.state == "open"
    assert row.active is True
    assert row.occurrence_count >= 1
