from flask import g
from sqlalchemy import select

from scheduler import logic, model
from scheduler.app import admin_only, login_required
from scheduler.auth import authorization
from scheduler.auth.authorization import require_permission
from scheduler.auth.models import SessionUser
from scheduler.auth.session import login_test_user, require_jwt


def test_login_test_user_admin_profile(app_context):
    if model.get(model.Group, "admin") is None:
        model.db.session.add(
            model.Group(id="admin", label="admin", description="Admin", active=True)
        )
        model.db.session.flush()

    with app_context.test_request_context():
        user = login_test_user("admin")
    assert user is not None
    assert user.username == "test-admin"
    assert user.active is True

    db_user = model.get(model.User, "test-admin")
    assert db_user is not None
    assert db_user.active is True
    assert model.get(model.GroupMember, ("admin", "test-admin")) is not None


def test_login_test_user_member_profile(app_context):
    with app_context.test_request_context():
        user = login_test_user("member")
    assert user is not None
    assert user.username == "test-member"
    assert user.active is True
    assert model.get(model.GroupMember, ("admin", "test-member")) is None


def test_login_test_user_dev_profile_has_dev_membership(app_context):
    with app_context.test_request_context():
        user = login_test_user("dev")
    assert user is not None
    assert user.username == "test-dev"
    assert user.active is True

    membership = model.get(model.GroupMember, ("DEV", "test-dev"))
    assert membership is not None
    assert membership.approved is not None
    assert model.get(model.Technologist, "test-dev") is None
    assert model.get(model.UserDevice, ("test-dev", "TEST")) is None


def test_login_test_user_tech_profile_has_tech_privileges(app_context):
    with app_context.test_request_context():
        user = login_test_user("tech")
    assert user is not None
    assert user.username == "test-tech"
    assert user.active is True

    membership = model.get(model.GroupMember, ("DEV", "test-tech"))
    assert membership is not None
    assert membership.approved is not None
    assert model.get(model.Technologist, "test-tech") is not None

    perms = model.get(model.UserDevice, ("test-tech", "TEST"))
    assert perms is not None
    assert perms.tech is True
    assert perms.templates is False
    assert perms.slot is False
    assert perms.medical is False
    assert perms.training is False


def test_login_required(app):
    @app.route("/protected")
    @login_required
    def protected():
        return "protected"

    client = app.test_client()
    response = client.get("/protected")
    assert response.status_code == 401


def test_admin_only(app):
    @app.route("/admin")
    @admin_only
    def admin():
        return "admin only"

    client = app.test_client()
    response = client.get("/admin")
    assert response.status_code == 401


def test_require_jwt_uses_existing_user(app):
    @app.route("/jwt-protected")
    @require_jwt
    def jwt_protected():
        return "ok"

    @app.before_request
    def set_request_user():
        g.user = SessionUser(username="test", email="test@example.com")

    client = app.test_client()
    response = client.get("/jwt-protected")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_require_jwt_rejects_unauthenticated_requests(app):
    @app.route("/jwt-protected-unauth")
    @require_jwt
    def jwt_protected_unauth():
        return "ok"

    client = app.test_client()
    response = client.get("/jwt-protected-unauth")
    assert response.status_code == 401


def test_require_permission_admin_allows(app, monkeypatch):
    @app.route("/admin-required")
    @require_permission("admin")
    def admin_required():
        return "ok"

    @app.before_request
    def set_request_user():
        g.user = SessionUser(username="test", email="test@example.com")

    monkeypatch.setattr(logic, "is_admin", lambda u: True)
    monkeypatch.setattr(
        authorization,
        "get_user_by_email",
        lambda email: type("U", (), {"id": "u1", "email": email, "active": True}),
    )

    client = app.test_client()
    response = client.get("/admin-required")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_require_permission_admin_blocks(app, monkeypatch):
    @app.route("/admin-blocked")
    @require_permission("admin")
    def admin_blocked():
        return "ok"

    @app.before_request
    def set_request_user():
        g.user = SessionUser(username="test", email="test@example.com")

    monkeypatch.setattr(logic, "is_admin", lambda u: False)
    monkeypatch.setattr(
        authorization,
        "get_user_by_email",
        lambda email: type("U", (), {"id": "u1", "email": email, "active": True}),
    )

    client = app.test_client()
    response = client.get("/admin-blocked")
    assert response.status_code == 403


def test_upsert_user_avoids_local_part_collisions(app_context):
    first = logic.upsert_user("alice", "alice@dept-one.example", "Alice One")
    second = logic.upsert_user("alice", "alice@dept-two.example", "Alice Two")
    model.db.session.flush()

    assert first.id == "alice"
    assert first.addr == "alice@dept-one.example"
    assert second.id != first.id
    assert second.addr == "alice@dept-two.example"
    assert len(second.id) <= 20


def test_upsert_user_reuses_existing_record_for_same_email(app_context):
    first = logic.upsert_user("alias-one", "same.user@example.com", "Same User")
    second = logic.upsert_user("alias-two", "same.user@example.com", "Updated Name")
    model.db.session.flush()

    assert second.id == first.id
    assert second.addr == "same.user@example.com"
    assert second.label == "Updated Name"


def test_upsert_user_proactively_migrates_to_requested_id(app_context):
    if model.get(model.Group, "DEV") is None:
        model.db.session.add(
            model.Group(id="DEV", label="DEV", description="DEV", active=True)
        )
        model.db.session.flush()

    legacy_id = "legacy-migrate"
    email = "contact006@example.org"
    target_id = logic.scoped_user_id_from_identifier(email)
    assert legacy_id != target_id

    model.db.session.add(
        model.User(id=legacy_id, label="Legacy User", addr=email, active=True)
    )
    model.db.session.flush()
    model.db.session.add(model.GroupMember(group="DEV", user=legacy_id))
    model.db.session.flush()

    migrated = logic.upsert_user(
        target_id,
        email,
        "Migrated User",
        migrate_to_requested_id=True,
    )
    model.db.session.flush()

    assert migrated.id == target_id
    assert model.get(model.GroupMember, ("DEV", target_id)) is not None
    assert model.get(model.GroupMember, ("DEV", legacy_id)) is None

    canonical = model.db.session.execute(
        select(model.User).where(model.User.addr == email)
    ).scalar_one_or_none()
    assert canonical is not None
    assert canonical.id == target_id
