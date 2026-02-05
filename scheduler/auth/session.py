# scheduler/auth/session.py

from typing import Dict, Optional

from flask import abort, current_app, g, request, session
from functools import wraps

from scheduler import model
from scheduler.logic import upsert_user

from .jwt_utils import extract_bearer_token, user_from_claims, verify_jwt
from .models import SessionUser


def _persist_user(user: SessionUser) -> None:
    """Ensure the user exists in the local database."""
    upsert_user(user.username, user.email, user.display_name)
    model.db.session.commit()


def _store_session(user: SessionUser) -> None:
    """Store the authenticated user in the Flask session."""
    session.permanent = True
    session["user_name"] = user.username
    session["display_name"] = user.display_name
    session["email"] = user.email
    session["groups"] = user.groups


def authenticate_bearer_token(
    auth_header: Optional[str], *, persist_session: bool = False
) -> Optional[SessionUser]:
    """Authenticate a request using a Bearer token."""
    token = extract_bearer_token(auth_header)
    if not token:
        return None

    claims, error = verify_jwt(token)
    if error:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT verification failed: %s", error)
        return None

    user = user_from_claims(claims)
    if not user:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims missing email")
        return None

    _persist_user(user)
    if persist_session:
        _store_session(user)

    return user


def login_user_with_token(token: str) -> Optional[SessionUser]:
    """Create a session from a validated JWT token."""
    claims, error = verify_jwt(token)
    if error:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT verification failed during login: %s", error)
        return None

    user = user_from_claims(claims)
    if not user:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims missing email during login")
        return None

    _persist_user(user)
    _store_session(user)
    g.user = user
    return user


def login_user_with_claims(claims: Dict) -> Optional[SessionUser]:
    """Create a session from already-validated JWT claims."""
    user = user_from_claims(claims)
    if not user:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims missing email during login")
        return None

    _persist_user(user)
    _store_session(user)
    g.user = user
    return user


def logout_user() -> None:
    """Log out current user."""
    session.pop("user_name", None)
    session.pop("display_name", None)
    session.pop("email", None)
    session.pop("groups", None)
    if hasattr(g, "user"):
        delattr(g, "user")


def get_user_from_session() -> Optional[SessionUser]:
    """Get user from current session if present."""
    username = session.get("user_name")
    email = session.get("email")
    display_name = session.get("display_name", "")
    groups = session.get("groups", [])

    if not username or not email:
        return None

    return SessionUser(
        username=username,
        email=email,
        display_name=display_name,
        groups=groups,
    )


def require_jwt(fn):
    """Decorator to enforce JWT authentication (Bearer or established session)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Already authenticated in request context
        if getattr(g, "user", None):
            return fn(*args, **kwargs)

        # Try bearer token
        bearer_user = authenticate_bearer_token(
            request.headers.get("Authorization"), persist_session=False
        )
        if bearer_user:
            g.user = bearer_user
            return fn(*args, **kwargs)

        # Try existing server session (set by /auth/session)
        session_user = get_user_from_session()
        if session_user:
            g.user = session_user
            return fn(*args, **kwargs)

        abort(401, "Access denied: Authentication required")

    return wrapper
