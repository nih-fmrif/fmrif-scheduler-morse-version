import pytest

from scheduler import logic, model
from scheduler.auth.views import auth
from scheduler.config import settings

pytestmark = pytest.mark.route


def _register_auth_blueprint(app):
    if "auth" not in app.blueprints:
        app.register_blueprint(auth, url_prefix="/auth")


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

    if model.Group.query.get("admin") is None:
        model.db.session.add(
            model.Group(id="admin", label="admin", description="Admin", active=True)
        )
        model.db.session.commit()

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json={"profile": "admin"},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-admin"
    assert payload["active"] is True

    with client.session_transaction() as sess:
        assert sess.get("user_name") == "test-admin"
        assert sess.get("email") == "test-admin@example.com"


@pytest.mark.covers_route("/auth/test/session", "DELETE")
def test_test_session_delete_clears_session(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    if model.Group.query.get("admin") is None:
        model.db.session.add(
            model.Group(id="admin", label="admin", description="Admin", active=True)
        )
        model.db.session.commit()

    client = app_context.test_client()
    create_response = client.post(
        "/auth/test/session",
        json={"profile": "admin"},
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
        json={"profile": "dev"},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-dev"
    assert payload["active"] is True

    with client.session_transaction() as sess:
        assert sess.get("user_name") == "test-dev"
        assert sess.get("email") == "test-dev@example.com"
    dev_user = model.User.query.get("test-dev")
    assert dev_user is not None
    assert logic.show_tech_join_form(dev_user) is True


def test_test_session_tech_profile_has_seeded_tech_access(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")

    client = app_context.test_client()
    response = client.post(
        "/auth/test/session",
        json={"profile": "tech"},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "test-tech"
    assert payload["active"] is True

    assert model.Technologist.query.get("test-tech") is not None
    perms = model.UserDevice.query.get(("test-tech", "TEST"))
    assert perms is not None
    assert perms.tech is True
    tech_user = model.User.query.get("test-tech")
    assert tech_user is not None
    assert logic.show_tech_join_form(tech_user) is False
