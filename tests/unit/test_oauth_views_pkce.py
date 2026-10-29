from urllib.parse import parse_qs, urlparse

from flask import Flask

from scheduler import model
from scheduler.auth import views
from scheduler.auth.views import auth
from scheduler.config import app_config, settings


def _build_test_app() -> Flask:
    app = Flask(__name__)
    app.config.update(**dict(app_config))
    app.config["TESTING"] = True
    app.register_blueprint(auth, url_prefix="/auth")
    return app


def test_start_login_redirect_contains_pkce_params(monkeypatch):
    app = _build_test_app()

    captured = {}

    def fake_create_oauth_state(next_url, code_verifier):
        captured["next_url"] = next_url
        captured["code_verifier"] = code_verifier
        return "state-123", "nonce-123"

    monkeypatch.setattr(views, "_create_oauth_state", fake_create_oauth_state)
    monkeypatch.setattr(
        views,
        "get_authorization_endpoint",
        lambda: "https://login.example.test/authorize",
    )
    monkeypatch.setattr(settings.entra, "client_id", "client-id")
    monkeypatch.setattr(settings.entra, "client_secret", "client-secret")
    monkeypatch.setattr(
        settings.entra, "redirect_uri", "https://app.example.test/auth/callback"
    )
    monkeypatch.setattr(settings.entra, "scope", "openid profile email")

    client = app.test_client()
    response = client.get("/auth/entra?next=%2Fdevices")

    assert response.status_code == 302
    location = response.headers["Location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)

    assert params["state"] == ["state-123"]
    assert params["nonce"] == ["nonce-123"]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params
    assert captured["next_url"] == "/devices"
    assert captured["code_verifier"]


def test_exchange_code_for_token_sends_code_verifier(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"id_token": "header.payload.sig"}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        views, "get_token_endpoint", lambda: "https://login.example.test/token"
    )
    monkeypatch.setattr(views.requests, "post", fake_post)
    monkeypatch.setattr(settings.entra, "client_id", "client-id")
    monkeypatch.setattr(settings.entra, "client_secret", "client-secret")
    monkeypatch.setattr(
        settings.entra, "redirect_uri", "https://app.example.test/auth/callback"
    )

    token = views._exchange_code_for_token("auth-code", "pkce-verifier")

    assert token == {"id_token": "header.payload.sig"}
    assert captured["url"] == "https://login.example.test/token"
    assert captured["timeout"] == 10
    assert captured["data"]["code_verifier"] == "pkce-verifier"


def test_consume_oauth_state_returns_and_deletes_code_verifier(app_context):
    record = model.OAuthState(
        state="state-delete-me",
        nonce="nonce-delete-me",
        redirect_next="/devices",
        code_verifier="pkce-delete-me",
    )
    model.db.session.add(record)
    model.db.session.commit()

    payload = views._consume_oauth_state("state-delete-me")

    assert payload is not None
    assert payload["code_verifier"] == "pkce-delete-me"
    assert (
        model.OAuthState.query.filter_by(state="state-delete-me").one_or_none() is None
    )


def test_create_oauth_state_persists_code_verifier(app_context):
    state, nonce = views._create_oauth_state("/devices", "pkce-persist-me")

    assert state is not None
    assert nonce is not None
    record = model.OAuthState.query.filter_by(state=state).one_or_none()
    assert record is not None
    assert record.code_verifier == "pkce-persist-me"
