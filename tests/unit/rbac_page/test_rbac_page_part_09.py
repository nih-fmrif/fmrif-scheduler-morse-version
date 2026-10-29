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

import scheduler.logic.rbac_audit_support as logic
import scheduler.message as scheduler_message
from scheduler import model
from scheduler.routes import rbac_routes

pytestmark = [pytest.mark.route, pytest.mark.xdist_group("mailpit")]


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


def test_app_issues_scan_expires_old_resolved_notification_incidents(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    issue_key = f"expired-test:{uuid.uuid4().hex[:10]}"
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=(365 * 5) + 3
    )
    model.db.session.add(
        model.NotificationIncident(
            issue_key=issue_key,
            issue_type="retention-test",
            category="notifications",
            severity="warning",
            title="expired issue",
            detail="expired issue detail",
            href=None,
            link_label="",
            active=False,
            state="resolved",
            state_note="old incident",
            state_changed_by="system",
            state_changed_at=old_time,
            ignored_until=None,
            first_seen_at=old_time,
            last_seen_at=old_time,
            last_detected_at=old_time,
            last_resolved_at=old_time,
            occurrence_count=1,
            fingerprint="retention-test",
        )
    )
    model.db.session.commit()

    _run_notification_scan(route_client)

    expired = model.db.session.get(model.NotificationIncident, issue_key)
    assert expired is None


@pytest.mark.covers_route("/app/issues/notifications/state", "POST")
def test_app_issues_notification_state_requires_note(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"statenote-{uuid.uuid4().hex[:6]}"
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
    page = route_client.get("/app/issues")
    csrf_token = extract_csrf_token(page.get_data(as_text=True))
    response = route_client.post(
        "/app/issues/notifications/state",
        data={
            "csrf_token": csrf_token,
            "issue_key": issue_key,
            "target_state": "ignored",
            "note": "",
            "return_query": "",
        },
    )
    assert response.status_code == 400


def test_app_issues_notification_state_sets_ignored_and_respects_expiry(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"ignore-{uuid.uuid4().hex[:6]}"
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
    page = route_client.get("/app/issues")
    csrf_token = extract_csrf_token(page.get_data(as_text=True))
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    response = route_client.post(
        "/app/issues/notifications/state",
        data={
            "csrf_token": csrf_token,
            "issue_key": issue_key,
            "target_state": "ignored",
            "note": "temporary suppress while owner validates mail routing",
            "ignored_until": yesterday.isoformat(),
            "return_query": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    ignored = model.db.session.get(model.NotificationIncident, issue_key)
    assert ignored is not None
    assert ignored.state == "ignored"
    assert ignored.active is True
    assert ignored.ignored_until is not None

    _run_notification_scan(route_client)

    reopened = model.db.session.get(model.NotificationIncident, issue_key)
    assert reopened is not None
    assert reopened.state == "open"
    assert reopened.active is True


def test_app_issues_scan_auto_resolves_and_reopens_new_occurrence(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    requester_id = f"cycle-{uuid.uuid4().hex[:6]}"
    ensure_active_user(requester_id, f"{requester_id}@example.com", requester_id)
    row = model.GroupMember(
        group=group_id,
        user=requester_id,
        approved=None,
        email_status="failed",
    )
    model.db.session.add(row)
    model.db.session.commit()

    _run_notification_scan(route_client)
    issue_key = f"join-group:{group_id}:{requester_id}"
    first = model.db.session.get(model.NotificationIncident, issue_key)
    assert first is not None
    first_occurrence = int(first.occurrence_count)
    assert first.state == "open"
    assert first.active is True

    row.email_status = "sent"
    model.db.session.add(row)
    model.db.session.commit()
    _run_notification_scan(route_client)

    resolved = model.db.session.get(model.NotificationIncident, issue_key)
    assert resolved is not None
    assert resolved.state == "resolved"
    assert resolved.active is False

    row.email_status = "failed"
    model.db.session.add(row)
    model.db.session.commit()
    _run_notification_scan(route_client)

    reopened = model.db.session.get(model.NotificationIncident, issue_key)
    assert reopened is not None
    assert reopened.state == "open"
    assert reopened.active is True
    assert int(reopened.occurrence_count) == first_occurrence + 1


def test_app_issues_page_allows_searching_resolved_notification_history(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    issue_key = f"join-group:DEV:resolved-{uuid.uuid4().hex[:6]}"
    logic.log_email_audit_event(
        action="email.issue.resolved",
        actor="test-admin",
        where="/rbac?scope=group&entity=DEV",
        how="rbac-explorer-batch",
        status=logic.EMAIL_AUDIT_STATUS_RESOLVED,
        recipient="-",
        subject="notification issue resolved",
        details="group=DEV, requester=resolved-user, email_status=failed->sent",
        issue_key=issue_key,
        issue_state=logic.EMAIL_AUDIT_ISSUE_RESOLVED,
    )
    model.db.session.commit()

    response = route_client.get(
        f"/app/issues?email_issue_state=resolved&email_search_field=issue_key&email_search={issue_key}"
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Email audit log" in body
    assert issue_key in body
    assert "notification issue resolved" in body


def test_app_issues_page_allows_searching_email_audit_history(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    recipient_id = f"recip-{uuid.uuid4().hex[:6]}"
    logic.log_email_audit_event(
        action="email.scheduler.notification",
        actor="test-admin",
        where="/app",
        how="unit-test",
        status=logic.EMAIL_AUDIT_STATUS_SENT,
        recipient=recipient_id,
        subject="unit test email audit history",
        details="recipient search test",
        issue_state=logic.EMAIL_AUDIT_ISSUE_RESOLVED,
    )
    logic.log_email_audit_event(
        action="email.scheduler.notification",
        actor="test-admin",
        where="/app",
        how="unit-test",
        status=logic.EMAIL_AUDIT_STATUS_FAILED,
        recipient="other@example.com",
        subject="other test email",
        details="other recipient",
        issue_state=logic.EMAIL_AUDIT_ISSUE_OPEN,
    )
    model.db.session.commit()

    response = route_client.get(
        f"/app/issues?email_issue_state=all&email_search_field=recipient&email_search={recipient_id}"
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Email audit log" in body
    assert recipient_id in body
    assert "unit test email audit history" in body
    assert "RBAC audit log" not in body


@pytest.mark.covers_route("/json/v1/rbac/audit", "GET")
def test_rbac_audit_api_returns_filtered_results_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    actor_id = f"rf{uuid.uuid4().hex[:6]}"
    logic.log_rbac_audit_event(
        action="group.member.update",
        actor=actor_id,
        where="/rbac?scope=group&entity=DEV",
        how="rbac-explorer-batch",
        what="group=DEV, user=feed-user, approved=true",
    )
    logic.log_rbac_audit_event(
        action="group.member.update",
        actor="nomatch2",
        where="/rbac?scope=group&entity=DEV",
        how="rbac-explorer-batch",
        what="group=DEV, user=feed-user-2, approved=true",
    )
    model.db.session.commit()

    response = route_client.get(
        f"/json/v1/rbac/audit?scope=all&search_field=actor&search={actor_id}"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["count"] == 1
    assert len(payload["events"]) == 1
    assert payload["events"][0]["actor"] == actor_id
