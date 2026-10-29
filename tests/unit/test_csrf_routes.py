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
from scheduler.app import app
from scheduler.auth.models import SessionUser

pytestmark = pytest.mark.route


def _prepare_pending_join_request() -> tuple[str, str, str]:
    candidate_id = f"cand-{uuid.uuid4().hex[:6]}"
    group_id = f"G{uuid.uuid4().hex[:5]}"

    ensure_group(group_id, label=group_id, description=f"Group {group_id}", active=True)
    ensure_active_user("test-admin", "test-admin@example.com", "Test Admin")
    ensure_active_user(candidate_id, "candidate-no-email", "Candidate")
    set_group_membership(group_id, "test-admin", approved=True, pi=True)
    set_group_membership(group_id, candidate_id, approved=False, pi=False)

    with app.test_request_context():
        token = logic.sign_message(["join-group", candidate_id, group_id])

    return token, candidate_id, group_id


def _install_realistic_route_auth(monkeypatch):
    monkeypatch.setattr(app, "session_interface", SecureCookieSessionInterface())
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


def test_join_request_decision_get_requires_confirmation(monkeypatch):
    _install_realistic_route_auth(monkeypatch)
    token, _, _ = _prepare_pending_join_request()

    client = app.test_client()
    response = client.get(
        f"/join/approve/{token}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 200
    assert b"Confirm that you want to approve" in response.data


def test_join_request_decision_post_rejects_missing_csrf(monkeypatch):
    _install_realistic_route_auth(monkeypatch)
    token, candidate_id, group_id = _prepare_pending_join_request()

    client = app.test_client()
    response = client.post(
        f"/join/approve/{token}",
        data={},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 400

    with app.app_context():
        req = model.GroupMember.query.get((group_id, candidate_id))
        assert req is not None
        assert req.approved is None


@pytest.mark.covers_route("/join/approve/<token>", "POST")
def test_join_request_decision_post_with_csrf_applies_update(monkeypatch):
    _install_realistic_route_auth(monkeypatch)
    token, candidate_id, group_id = _prepare_pending_join_request()

    client = app.test_client()
    headers = {"Authorization": "Bearer fake-token"}
    get_response = client.get(f"/join/approve/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/join/approve/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    with app.app_context():
        req = model.GroupMember.query.get((group_id, candidate_id))
        assert req is not None
        assert req.approved is not None


@pytest.mark.covers_route("/join/deny/<token>", "POST")
def test_join_request_deny_post_with_csrf_deletes_request(monkeypatch):
    _install_realistic_route_auth(monkeypatch)
    token, candidate_id, group_id = _prepare_pending_join_request()

    client = app.test_client()
    headers = {"Authorization": "Bearer fake-token"}
    get_response = client.get(f"/join/deny/{token}", headers=headers)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/join/deny/{token}",
        data={"csrf_token": csrf_token},
        headers=headers,
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    with app.app_context():
        req = model.GroupMember.query.get((group_id, candidate_id))
        assert req is None
