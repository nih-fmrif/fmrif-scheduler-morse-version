import socket
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
    ensure_active_user,
    ensure_group,
    extract_csrf_token,
    set_group_membership,
    set_session_user,
)
from sqlalchemy import select

import scheduler.message as scheduler_message
from scheduler import logic, model


def _capture_rbac_events(monkeypatch) -> list[tuple[str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str]] = []

    def capture(action: str, actor: str, where: str, how: str, what: str) -> None:
        events.append((action, actor, where, how, what))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


def _latest_email_audit(*criteria):
    statement = select(model.EmailAuditLog).order_by(model.EmailAuditLog.id.desc())
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).first()


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Mailpit API config missing. Set MAILPIT__PORT or MAILPIT_API_BASE_URL."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API not reachable at {cfg.api_base_url}.")
    return cfg


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


pytestmark = pytest.mark.route


@pytest.mark.covers_route("/mailing-lists", "POST")
def test_mailing_lists_post_delivers_to_mailpit_api(route_app, route_client):
    cfg = _require_mailpit()

    user_id = f"list-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@nih.gov"
    ensure_active_user(user_id, email, "List User")
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="List User",
    )

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
            get_response = route_client.get("/mailing-lists")
            csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

            post_response = route_client.post(
                "/mailing-lists",
                data={
                    "csrf_token": csrf_token,
                    "addr": email,
                    "name": "List User",
                    "action": "sub",
                    "lists-ml-0": "y",
                },
                follow_redirects=False,
            )

            assert post_response.status_code == 302
            assert post_response.headers["Location"].endswith("/")
            persisted = _latest_email_audit(
                model.EmailAuditLog.action == "email.mailing-list.change"
            )
            assert persisted is not None
            assert persisted.requester == email
            assert persisted.status == logic.EMAIL_AUDIT_STATUS_SENT

            summary = wait_for_mailpit_message(
                cfg,
                lambda item: item.get("Subject") == "Automated list change",
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))

            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower()
                == logic.get_admin_listserv().lower()
                for recipient in recipients
                if isinstance(recipient, dict)
            )

            sender = detail.get("From", {})
            assert isinstance(sender, dict)
            assert str(sender.get("Address", "")).lower() == email.lower()
            assert "subscribe" in str(detail.get("Text", "")).lower()
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/join", "POST")
def test_join_post_creates_pending_membership_request(
    monkeypatch, route_app, route_client, route_app_context
):
    cfg = _require_mailpit()

    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    pi_id = f"pi-{uuid.uuid4().hex[:6]}"
    pi_email = f"{pi_id}@example.com"
    ensure_active_user(pi_id, pi_email, "Group PI")
    set_group_membership(group_id, pi_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

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
            get_response = route_client.get("/join")
            csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
            events = _capture_rbac_events(monkeypatch)

            post_response = route_client.post(
                "/join",
                data={
                    "csrf_token": csrf_token,
                    "group": group_id,
                },
                follow_redirects=False,
            )

            assert post_response.status_code == 302
            assert post_response.headers["Location"].endswith("/")
            req = model.get(model.GroupMember, (group_id, requester_id))
            assert req is not None
            assert req.approved is None
            assert req.email_status == "sent"
            assert len(events) == 1
            action, actor, where, how, what = events[0]
            assert action == "group.join.request"
            assert actor == requester_id
            assert where == f"/join/{group_id}"
            assert how == "email"
            assert f"group={group_id}" in what

            audit_row = _latest_email_audit(
                model.EmailAuditLog.action == "email.join.notify-group-pi",
                model.EmailAuditLog.requester == requester_id,
            )
            assert audit_row is not None
            assert audit_row.status == logic.EMAIL_AUDIT_STATUS_SENT
            assert audit_row.issue_state == logic.EMAIL_AUDIT_ISSUE_NONE
            assert audit_row.issue_key == f"join-group:{group_id}:{requester_id}"

            expected_subject = f"{requester_id} has requested to join {group_id}"
            summary = wait_for_mailpit_message(
                cfg,
                lambda row: row.get("Subject") == expected_subject,
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))
            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower() == pi_email.lower()
                for recipient in recipients
                if isinstance(recipient, dict)
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/join", "POST")
def test_join_post_survives_mail_transport_failure(
    monkeypatch, route_app, route_client, route_app_context
):
    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    pi_id = f"pi-{uuid.uuid4().hex[:6]}"
    pi_email = f"{pi_id}@example.com"
    ensure_active_user(pi_id, pi_email, "Group PI")
    set_group_membership(group_id, pi_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

    with _route_mail_config(
        route_app,
        MAIL_SERVER="127.0.0.1",
        MAIL_PORT=_unused_local_port(),
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        get_response = route_client.get("/join")
        csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
        events = _capture_rbac_events(monkeypatch)

        post_response = route_client.post(
            "/join",
            data={
                "csrf_token": csrf_token,
                "group": group_id,
            },
            follow_redirects=False,
        )

        assert post_response.status_code == 302
        assert post_response.headers["Location"].endswith("/")
        req = model.get(model.GroupMember, (group_id, requester_id))
        assert req is not None
        assert req.approved is None
        assert req.email_status == "failed"
        assert len(events) == 1
        action, actor, where, how, what = events[0]
        assert action == "group.join.request"
        assert actor == requester_id
        assert where == f"/join/{group_id}"
        assert how == "email"
        assert f"group={group_id}" in what

        audit_row = _latest_email_audit(
            model.EmailAuditLog.action == "email.join.notify-group-pi",
            model.EmailAuditLog.requester == requester_id,
        )
        assert audit_row is not None
        assert audit_row.status == logic.EMAIL_AUDIT_STATUS_FAILED
        assert audit_row.issue_state == logic.EMAIL_AUDIT_ISSUE_OPEN
        assert audit_row.issue_key == f"join-group:{group_id}:{requester_id}"


@pytest.mark.covers_route("/join", "POST")
def test_join_post_without_group_pi_does_not_crash(
    monkeypatch, route_client, route_app_context
):
    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

    get_response = route_client.get("/join")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join",
        data={
            "csrf_token": csrf_token,
            "group": group_id,
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    req = model.get(model.GroupMember, (group_id, requester_id))
    assert req is not None
    assert req.approved is None
    assert req.email_status == "failed"
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.request"
    assert actor == requester_id
    assert where == f"/join/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what
    audit_row = _latest_email_audit(
        model.EmailAuditLog.action == "email.join.notify-group-pi",
        model.EmailAuditLog.requester == requester_id,
    )
    assert audit_row is None


@pytest.mark.covers_route("/join/tech", "POST")
def test_join_tech_post_autoapproves_technologist_request(
    monkeypatch, route_app, route_client, route_app_context
):
    cfg = _require_mailpit()

    user_id = f"tech-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Tech User")

    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Tech User",
    )

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
            get_response = route_client.get("/join/tech")
            csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
            events = _capture_rbac_events(monkeypatch)

            post_response = route_client.post(
                "/join/tech",
                data={"csrf_token": csrf_token},
                follow_redirects=False,
            )

            assert post_response.status_code == 302
            assert post_response.headers["Location"].endswith("/")
            req = model.get(model.Technologist, user_id)
            assert req is not None
            assert req.approved_on is not None
            assert req.email_status == logic.EMAIL_STATUS_NONE
            assert len(events) == 1
            action, actor, where, how, what = events[0]
            assert action == "group.join.tech.autoapprove"
            assert actor == user_id
            assert where == "/join/tech"
            assert how == "form"
            assert f"user={user_id}" in what
            assert "approved=true" in what

            audit_row = _latest_email_audit(
                model.EmailAuditLog.action == "email.join.tech.outcome",
                model.EmailAuditLog.actor == user_id,
            )
            assert audit_row is not None
            assert audit_row.status == logic.EMAIL_AUDIT_STATUS_SENT
            assert audit_row.issue_state == logic.EMAIL_AUDIT_ISSUE_NONE
            assert audit_row.issue_key in (None, "")
            assert audit_row.recipient.lower() == email.lower()

            expected_subject = "your request for technologist access was approved"
            summary = wait_for_mailpit_message(
                cfg,
                lambda row: row.get("Subject") == expected_subject,
                timeout_seconds=8.0,
                poll_interval_seconds=0.2,
            )
            assert summary is not None
            detail = get_mailpit_message(cfg, str(summary["ID"]))
            recipients = detail.get("To", [])
            assert isinstance(recipients, list)
            assert any(
                str(recipient.get("Address", "")).lower() == email.lower()
                for recipient in recipients
                if isinstance(recipient, dict)
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/join/tech", "POST")
def test_join_tech_post_without_dev_pi_still_autoapproves(
    monkeypatch, route_client, route_app_context
):
    user_id = f"tech-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Tech User")

    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    model.execute(
        "delete from primarygroupmember where deptcode = :group_id",
        {"group_id": "DEV"},
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Tech User",
    )

    get_response = route_client.get("/join/tech")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join/tech",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    req = model.get(model.Technologist, user_id)
    assert req is not None
    assert req.approved_on is not None
    assert req.email_status == logic.EMAIL_STATUS_NONE
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.tech.autoapprove"
    assert actor == user_id
    assert where == "/join/tech"
    assert how == "form"
    assert f"user={user_id}" in what
    assert "approved=true" in what

    requester_outcome = _latest_email_audit(
        model.EmailAuditLog.action == "email.join.tech.outcome",
        model.EmailAuditLog.actor == user_id,
    )
    assert requester_outcome is not None
    assert requester_outcome.status in {
        logic.EMAIL_AUDIT_STATUS_SENT,
        logic.EMAIL_AUDIT_STATUS_FAILED,
    }

    stale_dev_pi_notify = _latest_email_audit(
        model.EmailAuditLog.action == "email.join.tech.notify-dev-pi",
        model.EmailAuditLog.requester == user_id,
    )
    assert stale_dev_pi_notify is None
