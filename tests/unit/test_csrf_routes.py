import uuid

import pytest
from flask.sessions import SecureCookieSessionInterface
from route_seed import (
    ensure_active_user,
    ensure_group,
    extract_csrf_token,
    set_group_membership,
)

import scheduler.app as scheduler_app
from scheduler import logic, model
from scheduler.auth.models import SessionUser

pytestmark = pytest.mark.route


def _prepare_pending_join_request(route_app) -> tuple[str, str, str]:
    candidate_id = f"cand-{uuid.uuid4().hex[:6]}"
    group_id = f"G{uuid.uuid4().hex[:5]}"

    ensure_group(group_id, label=group_id, description=f"Group {group_id}", active=True)
    ensure_active_user("test-admin", "test-admin@example.com", "Test Admin")
    ensure_active_user(candidate_id, f"{candidate_id}-no-email", "Candidate")
    set_group_membership(group_id, "test-admin", approved=True, pi=True)
    set_group_membership(group_id, candidate_id, approved=False, pi=False)

    with route_app.test_request_context():
        token = logic.sign_message(["join-group", candidate_id, group_id])

    return token, candidate_id, group_id


def _prepare_pending_tech_join_request(route_app) -> tuple[str, str]:
    candidate_id = f"tech-{uuid.uuid4().hex[:6]}"

    ensure_group("DEV", label="DEV", description="Development Group", active=True)
    ensure_active_user("test-admin", "test-admin@example.com", "Test Admin")
    ensure_active_user(candidate_id, f"{candidate_id}@example.com", "Tech Candidate")
    set_group_membership("DEV", "test-admin", approved=True, pi=True)
    set_group_membership("DEV", candidate_id, approved=True, pi=False)
    model.db.session.add(
        model.Technologist(user=candidate_id, approved_on=None, email_status="sent")
    )
    model.db.session.flush()

    with route_app.test_request_context():
        token = logic.sign_message(["join-tech", candidate_id, "DEV"])

    return token, candidate_id


def _install_realistic_route_auth(monkeypatch, route_app):
    monkeypatch.setattr(route_app, "session_interface", SecureCookieSessionInterface())
    monkeypatch.setattr(
        scheduler_app,
        "authenticate_bearer_token",
        lambda auth_header: SessionUser(
            username="test-admin",
            email="test-admin@example.com",
            display_name="Test Admin",
            active=True,
        ),
    )
    monkeypatch.setattr(logic, "pi_of_group", lambda group_id: "test-admin")


def _capture_rbac_events(monkeypatch) -> list[tuple[str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str]] = []

    def capture(action: str, actor: str, where: str, how: str, what: str) -> None:
        events.append((action, actor, where, how, what))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


def test_join_request_decision_get_requires_confirmation(
    monkeypatch, route_app, route_client
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, _, _ = _prepare_pending_join_request(route_app)

    response = route_client.get(
        f"/join/approve/{token}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 200
    assert b"Confirm that you want to approve" in response.data


def test_join_request_decision_post_rejects_missing_csrf(
    monkeypatch, route_app, route_client, route_app_context
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, candidate_id, group_id = _prepare_pending_join_request(route_app)

    response = route_client.post(
        f"/join/approve/{token}",
        data={},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 400

    req = model.get(model.GroupMember, (group_id, candidate_id))
    assert req is not None
    assert req.approved is None


@pytest.mark.covers_route("/join/approve/<token>", "POST")
def test_join_request_decision_post_with_csrf_applies_update(
    monkeypatch, route_app, route_client, route_app_context
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, candidate_id, group_id = _prepare_pending_join_request(route_app)
    events = _capture_rbac_events(monkeypatch)

    headers = {"Authorization": "Bearer fake-token"}
    get_response = route_client.get(f"/join/approve/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/join/approve/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    req = model.get(model.GroupMember, (group_id, candidate_id))
    assert req is not None
    assert req.approved is not None
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.approve"
    assert actor == "test-admin"
    assert where == f"/join/approve/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what
    assert f"requester={candidate_id}" in what


@pytest.mark.covers_route("/join/deny/<token>", "POST")
def test_join_request_deny_post_with_csrf_deletes_request(
    monkeypatch, route_app, route_client, route_app_context
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, candidate_id, group_id = _prepare_pending_join_request(route_app)
    events = _capture_rbac_events(monkeypatch)

    headers = {"Authorization": "Bearer fake-token"}
    get_response = route_client.get(f"/join/deny/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/join/deny/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    req = model.get(model.GroupMember, (group_id, candidate_id))
    assert req is None
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.deny"
    assert actor == "test-admin"
    assert where == f"/join/deny/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what
    assert f"requester={candidate_id}" in what


def test_join_tech_request_decision_get_requires_confirmation(
    monkeypatch, route_app, route_client
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, _ = _prepare_pending_tech_join_request(route_app)

    response = route_client.get(
        f"/join/approve/{token}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 200
    assert b"Confirm that you want to approve" in response.data


@pytest.mark.covers_route("/join/approve/<token>", "POST")
def test_join_tech_request_approve_post_with_csrf_applies_update(
    monkeypatch, route_app, route_client, route_app_context
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, candidate_id = _prepare_pending_tech_join_request(route_app)
    events = _capture_rbac_events(monkeypatch)

    headers = {"Authorization": "Bearer fake-token"}
    get_response = route_client.get(f"/join/approve/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/join/approve/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    req = model.get(model.Technologist, candidate_id)
    assert req is not None
    assert req.approved_on is not None
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.tech.approve"
    assert actor == "test-admin"
    assert where == "/join/approve/DEV"
    assert how == "email"
    assert "group=DEV" in what
    assert f"requester={candidate_id}" in what


@pytest.mark.covers_route("/join/deny/<token>", "POST")
def test_join_tech_request_deny_post_with_csrf_deletes_request(
    monkeypatch, route_app, route_client, route_app_context
):
    _install_realistic_route_auth(monkeypatch, route_app)
    token, candidate_id = _prepare_pending_tech_join_request(route_app)
    events = _capture_rbac_events(monkeypatch)

    headers = {"Authorization": "Bearer fake-token"}
    get_response = route_client.get(f"/join/deny/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/join/deny/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    req = model.get(model.Technologist, candidate_id)
    assert req is None
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.tech.deny"
    assert actor == "test-admin"
    assert where == "/join/deny/DEV"
    assert how == "email"
    assert "group=DEV" in what
    assert f"requester={candidate_id}" in what
