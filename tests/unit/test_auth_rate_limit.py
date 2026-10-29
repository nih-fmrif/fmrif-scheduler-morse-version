from flask import Flask

import scheduler.auth.views as auth_views
from scheduler.auth.views import auth
from scheduler.config import settings


def _build_test_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(auth, url_prefix="/auth")
    return app


def test_auth_session_returns_429_when_rate_limited(monkeypatch):
    app = _build_test_app()
    monkeypatch.setattr(auth_views, "_is_auth_rate_limited", lambda _: True)

    client = app.test_client()
    response = client.post("/auth/session")

    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many authentication attempts"}


def test_auth_test_session_returns_429_when_rate_limited(monkeypatch):
    app = _build_test_app()
    monkeypatch.setattr(auth_views, "_is_auth_rate_limited", lambda _: True)
    monkeypatch.setattr(settings.auth_test, "enabled", True)

    client = app.test_client()
    response = client.post("/auth/test/session")

    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many authentication attempts"}


def test_auth_rate_limit_enforces_fixed_window(monkeypatch):
    app = _build_test_app()
    auth_views._AUTH_RATE_LIMIT_BUCKETS.clear()
    monkeypatch.setattr(settings.security, "auth_rate_limit_enabled", True)
    monkeypatch.setattr(settings.security, "auth_rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings.security, "auth_rate_limit_max_requests", 2)

    with app.test_request_context(
        "/auth/session", headers={"X-Forwarded-For": "203.0.113.15"}
    ):
        assert auth_views._is_auth_rate_limited("session") is False
        assert auth_views._is_auth_rate_limited("session") is False
        assert auth_views._is_auth_rate_limited("session") is True
