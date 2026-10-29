from datetime import datetime, timezone

import pytest
from flask import g
from route_seed import seeded_scanner_id, set_group_membership

from scheduler import logic, model
from scheduler.auth.views import auth
from scheduler.config import settings

pytestmark = pytest.mark.route


def _register_auth_blueprint(app):
    if "auth" not in app.blueprints:
        app.register_blueprint(auth, url_prefix="/auth")


def _session_payload(profile: str, session_key: str = "s1", **overrides):
    payload = {"profile": profile, "session_key": session_key}
    payload.update(overrides)
    return payload


def test_test_session_requires_secret(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post("/auth/test/session", json={"profile": "admin"})
    assert response.status_code == 403


@pytest.mark.covers_route("/auth/test/session", "POST")
def test_test_session_creates_profile_session(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    if model.get(model.Group, "admin") is None:
        model.db.session.add(
            model.Group(id="admin", label="admin", description="Admin", active=True)
        )
        model.db.session.flush()

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("admin"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-admin-s1"
    assert payload["active"] is True

    with client.session_transaction() as sess:
        assert sess.get("user_name") == "test-admin-s1"
        assert sess.get("email") == "test-admin+s1@example.com"


@pytest.mark.covers_route("/auth/test/session", "DELETE")
def test_test_session_delete_clears_session(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    if model.get(model.Group, "admin") is None:
        model.db.session.add(
            model.Group(id="admin", label="admin", description="Admin", active=True)
        )
        model.db.session.flush()

    client = app_context.test_client()
    create_response = client.post(
        "/auth/test/session",
        json=_session_payload("admin"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert create_response.status_code == 200

    delete_response = client.delete(
        "/auth/test/session",
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert delete_response.status_code == 204

    with client.session_transaction() as sess:
        assert sess.get("user_name") is None
        assert sess.get("email") is None


def test_test_session_dev_profile_allows_join_tech(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("dev"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-dev-s1"
    assert payload["active"] is True

    with client.session_transaction() as sess:
        assert sess.get("user_name") == "test-dev-s1"
        assert sess.get("email") == "test-dev+s1@example.com"
    dev_user = model.get(model.User, "test-dev-s1")
    assert dev_user is not None
    assert logic.show_tech_join_form(dev_user) is True


def test_test_session_dev_pi_profile_sets_dev_primary_group_membership(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("dev_pi"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-dev-pi-s1"
    assert payload["active"] is True

    membership = model.get(model.GroupMember, ("DEV", "test-dev-pi-s1"))
    assert membership is not None
    assert membership.approved is not None
    primary = model.get(model.PrimaryGroupMember, ("DEV", "test-dev-pi-s1"))
    assert primary is None


def test_test_session_member_profile_supports_explicit_group_pi_groups(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("member", group_pi_groups=["GPI"]),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-member-s1"
    assert payload["active"] is True

    membership = model.get(model.GroupMember, ("GPI", "test-member-s1"))
    assert membership is not None
    assert membership.approved is not None
    primary = model.get(model.PrimaryGroupMember, ("GPI", "test-member-s1"))
    assert primary is None


def test_test_session_reset_profile_state_clears_mock_auth_rows(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    seeded = client.post(
        "/auth/test/session",
        json=_session_payload("member"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert seeded.status_code == 200
    seeded_user = seeded.get_json()["username"]
    set_group_membership("DEV", seeded_user, approved=True, pi=True)
    model.db.session.add(
        model.Technologist(
            user=seeded_user,
            applied_on=datetime.now(timezone.utc),
            approved_on=datetime.now(timezone.utc),
            email_status="none",
        )
    )
    model.db.session.add(
        model.UserDevice(
            user=seeded_user,
            device=seeded_scanner_id(),
            templates=False,
            slot=False,
            tech=True,
            medical=False,
            training=False,
        )
    )
    model.db.session.commit()

    reset = client.post(
        "/auth/test/session",
        json=_session_payload("member", reset_profile_state=True),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert reset.status_code == 200

    assert model.get(model.GroupMember, ("DEV", seeded_user)) is None
    assert model.get(model.PrimaryGroupMember, ("DEV", seeded_user)) is None
    assert model.get(model.Technologist, seeded_user) is None
    assert model.get(model.UserDevice, (seeded_user, seeded_scanner_id())) is None


def test_test_session_session_key_isolates_parallel_mock_users(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    first = client.post(
        "/auth/test/session",
        json={
            "profile": "member",
            "session_key": "a1",
            "reset_profile_state": True,
        },
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert first.status_code == 200
    first_user = first.get_json()["username"]
    set_group_membership("DEV", first_user, approved=True, pi=False)

    second = client.post(
        "/auth/test/session",
        json={
            "profile": "member",
            "session_key": "b2",
            "reset_profile_state": True,
        },
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert second.status_code == 200
    second_user = second.get_json()["username"]

    assert first_user == "test-member-a1"
    assert second_user == "test-member-b2"
    assert model.get(model.GroupMember, ("DEV", first_user)) is not None
    assert model.get(model.GroupMember, ("DEV", second_user)) is None


def test_test_session_session_key_allows_parallel_dev_pi_sessions(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    first_client = app_context.test_client()
    second_client = app_context.test_client()
    first = first_client.post(
        "/auth/test/session",
        json={"profile": "dev_pi", "session_key": "a1", "reset_profile_state": True},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    second = second_client.post(
        "/auth/test/session",
        json={"profile": "dev_pi", "session_key": "b2", "reset_profile_state": True},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    first_user = first.get_json()["username"]
    second_user = second.get_json()["username"]

    if hasattr(g, "user"):
        delattr(g, "user")
    first_probe = first_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0&active=1"
    )
    if hasattr(g, "user"):
        delattr(g, "user")
    second_probe = second_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0&active=1"
    )
    assert first_probe.status_code == 200
    assert second_probe.status_code == 200

    first_payload = first_probe.get_json()
    second_payload = second_probe.get_json()
    assert {scope["id"] for scope in first_payload["scopes"]} == {"group", "device"}
    assert {scope["id"] for scope in second_payload["scopes"]} == {"group", "device"}

    first_membership = model.get(model.Membership, ("DEV", first_user))
    second_membership = model.get(model.Membership, ("DEV", second_user))
    assert first_membership is not None
    assert second_membership is not None
    assert first_membership.approved is True
    assert second_membership.approved is True
    assert first_membership.pi is False
    assert second_membership.pi is False
    assert model.get(model.PrimaryGroupMember, ("DEV", first_user)) is None
    assert model.get(model.PrimaryGroupMember, ("DEV", second_user)) is None


def test_test_session_rejects_invalid_session_key(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json={"profile": "member", "session_key": "bad!"},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == (
        "session_key must be 1-6 lowercase letters or digits"
    )


def test_test_session_rejects_missing_session_key(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json={"profile": "member"},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == (
        "session_key is required for auth test sessions"
    )


def test_test_session_rejects_non_boolean_reset_profile_state(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("member", reset_profile_state="yes"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "reset_profile_state must be a boolean"


def test_test_session_tech_profile_has_seeded_tech_access(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json=_session_payload("tech"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-tech-s1"
    assert payload["active"] is True

    assert model.get(model.Technologist, "test-tech-s1") is not None
    perms = model.get(model.UserDevice, ("test-tech-s1", "TEST"))
    assert perms is not None
    assert perms.tech is True
    tech_user = model.get(model.User, "test-tech-s1")
    assert tech_user is not None
    assert logic.show_tech_join_form(tech_user) is False


def test_test_session_member_profile_without_reset_keeps_existing_approved_dev_membership(
    app_context, monkeypatch
):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    first_login = client.post(
        "/auth/test/session",
        json=_session_payload("member"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert first_login.status_code == 200
    member_user = first_login.get_json()["username"]

    set_group_membership("DEV", member_user, approved=True, pi=False)
    row = model.get(model.GroupMember, ("DEV", member_user))
    assert row is not None
    assert row.approved is not None

    admin_switch = client.post(
        "/auth/test/session",
        json=_session_payload("admin"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert admin_switch.status_code == 200

    second_login = client.post(
        "/auth/test/session",
        json=_session_payload("member"),
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert second_login.status_code == 200

    persisted = model.get(model.GroupMember, ("DEV", member_user))
    assert persisted is not None
    assert persisted.approved is not None
