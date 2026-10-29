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

import scheduler.message as scheduler_message
from scheduler import logic, model
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


@pytest.mark.covers_route("/json/v1/email/audit", "GET")
def test_email_audit_api_returns_filtered_results_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    issue_key = f"join-group:DEV:api-{uuid.uuid4().hex[:6]}"
    logic.log_email_audit_event(
        action="email.issue.resolved",
        actor="test-admin",
        where="/rbac?scope=group&entity=DEV",
        how="rbac-explorer-batch",
        status=logic.EMAIL_AUDIT_STATUS_RESOLVED,
        recipient="-",
        subject="notification issue resolved",
        details="group=DEV, requester=api-user, email_status=failed->sent",
        issue_key=issue_key,
        issue_state=logic.EMAIL_AUDIT_ISSUE_RESOLVED,
    )
    logic.log_email_audit_event(
        action="email.scheduler.notification",
        actor="test-admin",
        where="/device/TEST",
        how="scheduler",
        status=logic.EMAIL_AUDIT_STATUS_FAILED,
        recipient="broken@example.com",
        subject="[scheduler] TEST: schedule change",
        details="device=TEST, stream=schedule",
    )
    model.db.session.commit()

    response = route_client.get(
        f"/json/v1/email/audit?scope=all&status=resolved&issue_state=resolved&search_field=issue_key&search={issue_key}"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["count"] == 1
    assert len(payload["events"]) == 1
    assert payload["events"][0]["issue_key"] == issue_key
    assert payload["events"][0]["status"] == "resolved"


@pytest.mark.covers_route("/json/v1/rbac/audit", "GET")
def test_rbac_audit_api_defaults_to_limit_10(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)

    captured: dict[str, int] = {}

    def fake_rows(scope: str, entity: str, *, limit: int, **_kwargs):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(logic, "rbac_audit_table_available", lambda: True)
    monkeypatch.setattr(rbac_routes, "_rbac_audit_rows", fake_rows)

    response = route_client.get("/json/v1/rbac/audit?scope=all")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["limit"] == 10
    assert captured["limit"] == 10


@pytest.mark.covers_route("/json/v1/rbac/audit", "GET")
def test_rbac_audit_api_rejects_limit_above_200(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)

    captured: dict[str, int] = {}

    def fake_rows(scope: str, entity: str, *, limit: int, **_kwargs):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(logic, "rbac_audit_table_available", lambda: True)
    monkeypatch.setattr(rbac_routes, "_rbac_audit_rows", fake_rows)

    response = route_client.get("/json/v1/rbac/audit?scope=all&limit=9999")
    assert response.status_code == 400
    assert captured == {}


def test_app_issues_page_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-audit-page"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User Audit Page")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User Audit Page",
    )

    response = route_client.get("/app/issues")
    assert response.status_code == 403


@pytest.mark.covers_route("/json/v1/rbac/audit", "GET")
def test_rbac_audit_api_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-audit"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User Audit")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User Audit",
    )

    response = route_client.get("/json/v1/rbac/audit?scope=group")
    assert response.status_code == 403


@pytest.mark.covers_route("/json/v1/email/audit", "GET")
def test_email_audit_api_forbidden_for_non_admin(route_client):
    user_id = "normal-user-email-audit"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User Email Audit")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User Email Audit",
    )

    response = route_client.get("/json/v1/email/audit?scope=all")
    assert response.status_code == 403
