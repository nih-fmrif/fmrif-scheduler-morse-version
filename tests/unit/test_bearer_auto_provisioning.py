from flask import Flask

import scheduler.auth.session as session_helpers
from scheduler.auth.models import SessionUser
from scheduler.config import EntraConfig, settings


def _build_test_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    return app


def test_authenticate_bearer_token_allows_existing_user_when_auto_provision_disabled(
    monkeypatch,
):
    app = _build_test_app()
    monkeypatch.setattr(
        settings,
        "entra",
        EntraConfig(bearer_auto_provision_enabled=False),
    )
    monkeypatch.setattr(session_helpers, "extract_bearer_token", lambda _: "token")
    monkeypatch.setattr(session_helpers, "verify_jwt", lambda _: ({"sub": "123"}, None))
    monkeypatch.setattr(
        session_helpers,
        "user_from_claims",
        lambda _: SessionUser(
            username="existing-user",
            email="contact007@example.org",
            display_name="Existing User",
        ),
    )
    monkeypatch.setattr(
        session_helpers,
        "_find_existing_user_by_email",
        lambda _: object(),
    )
    persist_calls = {"count": 0}
    monkeypatch.setattr(
        session_helpers,
        "_persist_user",
        lambda user: persist_calls.__setitem__("count", persist_calls["count"] + 1),
    )

    with app.test_request_context("/"):
        user = session_helpers.authenticate_bearer_token("Bearer token")

    assert user is not None
    assert persist_calls["count"] == 1


def test_authenticate_bearer_token_blocks_new_user_when_auto_provision_disabled(
    monkeypatch,
):
    app = _build_test_app()
    monkeypatch.setattr(
        settings,
        "entra",
        EntraConfig(bearer_auto_provision_enabled=False),
    )
    monkeypatch.setattr(session_helpers, "extract_bearer_token", lambda _: "token")
    monkeypatch.setattr(session_helpers, "verify_jwt", lambda _: ({"sub": "123"}, None))
    monkeypatch.setattr(
        session_helpers,
        "user_from_claims",
        lambda _: SessionUser(
            username="new-user",
            email="contact008@example.org",
            display_name="New User",
        ),
    )
    monkeypatch.setattr(session_helpers, "_find_existing_user_by_email", lambda _: None)
    monkeypatch.setattr(
        session_helpers,
        "_persist_user",
        lambda _: (_ for _ in ()).throw(AssertionError("should not persist new user")),
    )

    with app.test_request_context("/"):
        user = session_helpers.authenticate_bearer_token("Bearer token")

    assert user is None


def test_authenticate_bearer_token_applies_domain_and_group_policy(monkeypatch):
    app = _build_test_app()
    monkeypatch.setattr(
        settings,
        "entra",
        EntraConfig(
            bearer_auto_provision_enabled=True,
            bearer_auto_provision_domains=["example.org"],
            bearer_auto_provision_groups=["allowed-group"],
        ),
    )
    monkeypatch.setattr(session_helpers, "extract_bearer_token", lambda _: "token")
    monkeypatch.setattr(session_helpers, "verify_jwt", lambda _: ({"sub": "123"}, None))
    monkeypatch.setattr(
        session_helpers,
        "user_from_claims",
        lambda _: SessionUser(
            username="new-user",
            email="contact008@example.org",
            display_name="New User",
            groups=["allowed-group"],
        ),
    )
    monkeypatch.setattr(session_helpers, "_find_existing_user_by_email", lambda _: None)
    persist_calls = {"count": 0}
    monkeypatch.setattr(
        session_helpers,
        "_persist_user",
        lambda user: persist_calls.__setitem__("count", persist_calls["count"] + 1),
    )

    with app.test_request_context("/"):
        user = session_helpers.authenticate_bearer_token("Bearer token")

    assert user is not None
    assert persist_calls["count"] == 1


def test_login_user_with_token_blocks_new_user_when_auto_provision_disabled(
    monkeypatch,
):
    app = _build_test_app()
    monkeypatch.setattr(
        settings,
        "entra",
        EntraConfig(bearer_auto_provision_enabled=False),
    )
    monkeypatch.setattr(session_helpers, "verify_jwt", lambda _: ({"sub": "123"}, None))
    monkeypatch.setattr(
        session_helpers,
        "user_from_claims",
        lambda _: SessionUser(
            username="new-user",
            email="contact008@example.org",
            display_name="New User",
        ),
    )
    monkeypatch.setattr(session_helpers, "_find_existing_user_by_email", lambda _: None)
    monkeypatch.setattr(
        session_helpers,
        "_persist_user",
        lambda _: (_ for _ in ()).throw(AssertionError("should not persist new user")),
    )

    with app.test_request_context("/"):
        user = session_helpers.login_user_with_token("token")

    assert user is None
