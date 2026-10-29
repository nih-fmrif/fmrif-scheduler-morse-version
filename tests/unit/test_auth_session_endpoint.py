import pytest

import scheduler.auth.views as auth_views
from scheduler.auth.views import auth

pytestmark = pytest.mark.route


def _register_auth_blueprint(app):
    if "auth" not in app.blueprints:
        app.register_blueprint(auth, url_prefix="/auth")


@pytest.mark.covers_route("/auth/session", "POST")
def test_auth_session_missing_bearer_token_returns_401(app_context):
    _register_auth_blueprint(app_context)
    client = app_context.test_client()

    response = client.post("/auth/session")

    assert response.status_code == 401
    assert response.get_json() == {"error": "Missing bearer token"}


def test_auth_session_invalid_bearer_token_returns_401(app_context, monkeypatch):
    _register_auth_blueprint(app_context)
    monkeypatch.setattr(auth_views, "login_user_with_token", lambda _: None)
    client = app_context.test_client()

    response = client.post(
        "/auth/session",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid or expired token"}


def test_auth_session_valid_bearer_token_returns_identity(app_context, monkeypatch):
    _register_auth_blueprint(app_context)

    class _User:
        username = "route-user"
        email = "route-user@example.com"

    monkeypatch.setattr(auth_views, "login_user_with_token", lambda _: _User())
    client = app_context.test_client()

    response = client.post(
        "/auth/session",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "username": "route-user",
        "email": "route-user@example.com",
    }
