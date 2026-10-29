from types import SimpleNamespace

from flask import Flask, session
from flask.sessions import SecureCookieSessionInterface

import scheduler.auth.session as session_helpers
from scheduler.auth.models import SessionUser


def _build_test_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    return app


def test_store_session_rotates_identifier():
    app = _build_test_app()
    regenerated = {"count": 0}

    class _RotatingSessionInterface(SecureCookieSessionInterface):
        def regenerate(self, active_session):
            regenerated["count"] += 1
            active_session.sid = "rotated-session-id"
            active_session.modified = True

    app.session_interface = type(
        "_RotatingSessionInterface",
        (_RotatingSessionInterface,),
        {},
    )()

    with app.test_request_context("/"):
        session.sid = "original-session-id"
        user = SessionUser(
            username="session-user",
            email="session-user@example.com",
            display_name="Session User",
            groups=["DEV"],
        )

        session_helpers._store_session(user)

        assert regenerated["count"] == 1
        assert session.sid == "rotated-session-id"
        assert session["user_name"] == "session-user"
        assert session["email"] == "session-user@example.com"


def test_get_user_from_session_fails_closed_when_db_lookup_errors(monkeypatch):
    app = _build_test_app()

    def _raise(entity, _):
        assert entity is session_helpers.model.User
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session_helpers.model.db.session, "get", _raise)

    with app.test_request_context("/"):
        session["user_name"] = "danger-user"
        session["email"] = "danger-user@example.com"
        session["display_name"] = "Danger User"
        session["groups"] = ["DEV"]

        user = session_helpers.get_user_from_session()

        assert user is not None
        assert user.active is False


def test_persist_user_updates_session_identity_from_db_record(monkeypatch):
    app = _build_test_app()

    persisted = SimpleNamespace(
        id="scoped-user-id",
        addr="scoped.user@example.com",
        label="Scoped User",
    )

    def _mock_upsert(*_, **kwargs):
        assert kwargs.get("migrate_to_requested_id") is True
        return persisted

    monkeypatch.setattr(session_helpers, "upsert_user", _mock_upsert)
    monkeypatch.setattr(session_helpers.model.db.session, "commit", lambda: None)

    with app.test_request_context("/"):
        user = SessionUser(
            username="scoped",
            email="scoped.user@example.com",
            display_name="Scoped",
        )
        result = session_helpers._persist_user(user)

        assert result.username == "scoped-user-id"
        assert result.email == "scoped.user@example.com"
        assert result.display_name == "Scoped User"
