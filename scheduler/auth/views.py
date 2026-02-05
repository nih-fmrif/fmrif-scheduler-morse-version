"""Authentication views"""

import pickle
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from scheduler import model
from scheduler.config import settings

from .jwt_utils import extract_bearer_token, verify_jwt
from .oidc import get_authorization_endpoint, get_token_endpoint
from .session import get_user_from_session, login_user_with_claims, login_user_with_token, logout_user

# Create blueprint
auth = Blueprint("auth", __name__)

OAUTH_STATE_TTL_SECONDS = 10 * 60


@auth.route("/login", methods=["GET"])
def login():
    """Render OAuth login page."""
    if get_user_from_session():
        return redirect(url_for("home"))

    next_url = _safe_next_url(request.args.get("next"))

    return render_template("auth/login.html", next_url=next_url)


@auth.route("/callback")
def callback():
    """Handle OAuth redirect from Microsoft Entra."""
    logger = current_app.logger if current_app else None
    error = request.args.get("error")
    if error:
        if logger:
            logger.warning(
                "OAuth callback error: %s (%s)",
                error,
                request.args.get("error_description"),
            )
        flash("Login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        if logger:
            logger.warning("OAuth callback missing code parameter")
        flash("Missing authorization code. Please try again.", "error")
        return redirect(url_for("auth.login"))

    if not state:
        if logger:
            logger.warning("OAuth callback missing state parameter")
        flash("Invalid login state. Please try again.", "error")
        return redirect(url_for("auth.login"))

    oauth_state = _consume_oauth_state(state)
    if not oauth_state:
        if logger:
            logger.warning("OAuth state invalid or expired")
        flash("Invalid login state. Please try again.", "error")
        return redirect(url_for("auth.login"))

    token_response = _exchange_code_for_token(code)
    if not token_response:
        if logger:
            logger.warning("OAuth token exchange failed")
        flash("Login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    id_token = token_response.get("id_token")
    if not id_token:
        if logger:
            logger.warning("OAuth token exchange missing id_token")
        flash("Login failed. Missing ID token.", "error")
        return redirect(url_for("auth.login"))

    claims, error = verify_jwt(id_token)
    if error:
        if logger:
            logger.warning("OAuth id_token verification failed: %s", error)
        flash("Login failed. Invalid token.", "error")
        return redirect(url_for("auth.login"))

    if oauth_state.get("nonce") and claims.get("nonce") != oauth_state["nonce"]:
        if logger:
            logger.warning("OAuth nonce mismatch")
        flash("Login failed. Invalid token nonce.", "error")
        return redirect(url_for("auth.login"))

    user = login_user_with_claims(claims)
    if not user:
        if logger:
            logger.warning(
                "OAuth token missing email claim (available_claims=%s, has_preferred_username=%s, has_upn=%s)",
                sorted(claims.keys()),
                bool(claims.get("preferred_username")),
                bool(claims.get("upn")),
            )
        flash("Login failed. Missing email claim.", "error")
        return redirect(url_for("auth.login"))
    if logger:
        logger.info("OAuth login succeeded; session keys=%s", list(session.keys()))
    _force_persist_session(oauth_state.get("session_id"))

    next_url = oauth_state.get("redirect_next") or url_for("home")
    return render_template("auth/callback.html", next_url=next_url)


@auth.route("/entra")
def start_login():
    """Start server-side OAuth flow."""
    logger = current_app.logger if current_app else None
    if get_user_from_session():
        return redirect(url_for("home"))

    if not settings.entra.client_secret:
        if logger:
            logger.error("OAuth start blocked: client secret not configured")
        flash("Login unavailable: client secret not configured.", "error")
        return redirect(url_for("auth.login"))

    next_url = _safe_next_url(request.args.get("next"))
    session_store_id = _current_session_store_id()
    state, nonce = _create_oauth_state(next_url, session_store_id)
    if not state or not nonce:
        if logger:
            logger.error("OAuth start failed: unable to persist state")
        flash("Login unavailable. Please try again later.", "error")
        return redirect(url_for("auth.login"))

    try:
        auth_endpoint = get_authorization_endpoint()
    except Exception:
        if current_app and current_app.logger:
            current_app.logger.exception("Failed to load authorization endpoint")
        flash("Login unavailable. Please try again later.", "error")
        return redirect(url_for("auth.login"))
    if logger:
        logger.info(
            "Starting OAuth flow (redirect_uri=%s, scope=%s)",
            settings.entra.redirect_uri,
            settings.entra.scope,
        )
    params = {
        "client_id": settings.entra.client_id,
        "response_type": "code",
        "response_mode": "query",
        "redirect_uri": settings.entra.redirect_uri,
        "scope": settings.entra.scope,
        "state": state,
        "nonce": nonce,
    }
    return redirect(f"{auth_endpoint}?{urlencode(params)}")


@auth.route("/session", methods=["POST"])
def establish_session():
    """Create a server session from a validated JWT bearer token."""
    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        return jsonify({"error": "Missing bearer token"}), 401

    user = login_user_with_token(token)
    if not user:
        return jsonify({"error": "Invalid or expired token"}), 401

    return jsonify({"email": user.email, "username": user.username})


@auth.route("/logout")
def logout():
    """Handle user logout"""
    logout_user()
    flash("Successfully logged out", "success")
    return redirect(url_for("home"))


def _state_is_expired(created_at: Optional[datetime]) -> bool:
    if not created_at:
        return True
    if created_at.tzinfo:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.utcnow()
    return now - created_at > timedelta(seconds=OAUTH_STATE_TTL_SECONDS)


def _create_oauth_state(
    redirect_next: Optional[str], session_id: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    logger = current_app.logger if current_app else None
    for _ in range(3):
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        record = model.OAuthState(
            state=state,
            nonce=nonce,
            redirect_next=redirect_next,
            session_id=session_id,
        )
        model.db.session.add(record)
        try:
            model.db.session.commit()
            return state, nonce
        except IntegrityError:
            model.db.session.rollback()
        except SQLAlchemyError:
            model.db.session.rollback()
            if logger:
                logger.exception("Failed to persist OAuth state")
            return None, None
    if logger:
        logger.error("Failed to generate unique OAuth state after retries")
    return None, None


def _consume_oauth_state(state: str) -> Optional[dict]:
    logger = current_app.logger if current_app else None
    try:
        record = model.OAuthState.query.filter_by(state=state).one_or_none()
        if not record:
            return None

        if _state_is_expired(record.created_at):
            model.db.session.delete(record)
            model.db.session.commit()
            if logger:
                logger.warning("OAuth state expired")
            return None

        payload = {
            "nonce": record.nonce,
            "redirect_next": record.redirect_next,
            "session_id": record.session_id,
        }
        model.db.session.delete(record)
        model.db.session.commit()
        return payload
    except SQLAlchemyError:
        model.db.session.rollback()
        if logger:
            logger.exception("Failed to consume OAuth state")
        return None


def _force_persist_session(store_id_override: Optional[str] = None) -> None:
    logger = current_app.logger if current_app else None
    try:
        session_id = getattr(session, "sid", None)
        if not session_id:
            if logger:
                logger.warning("OAuth session persist skipped: missing session id")
            return
        interface = current_app.session_interface
        key_prefix = getattr(interface, "key_prefix", current_app.config.get("SESSION_KEY_PREFIX", "session:"))
        store_id = store_id_override or f"{key_prefix}{session_id}"
        expiry = interface.get_expiration_time(current_app, session)
        payload = pickle.dumps(dict(session))
        model.db.session.execute(
            text(
                "insert into site_sessions (session_id, data, expiry) "
                "values (:sid, :data, :expiry) "
                "on conflict (session_id) do update set data = :data, expiry = :expiry"
            ),
            {"sid": store_id, "data": payload, "expiry": expiry},
        )
        model.db.session.commit()
        if logger:
            try:
                decoded = pickle.loads(payload)
                decoded_keys = list(decoded.keys()) if isinstance(decoded, dict) else None
            except Exception:
                decoded_keys = None
        if logger:
            logger.info(
                "Persisted OAuth session payload (session_id=%s, keys=%s, decoded_keys=%s)",
                store_id,
                list(session.keys()),
                decoded_keys,
            )
    except Exception:
        model.db.session.rollback()
        if logger:
            logger.exception("Failed to persist OAuth session payload")


def _current_session_store_id() -> Optional[str]:
    session_id = getattr(session, "sid", None)
    if not session_id:
        return None
    interface = current_app.session_interface
    key_prefix = getattr(interface, "key_prefix", current_app.config.get("SESSION_KEY_PREFIX", "session:"))
    return f"{key_prefix}{session_id}"


def _exchange_code_for_token(code: str) -> Optional[dict]:
    logger = current_app.logger if current_app else None
    try:
        token_endpoint = get_token_endpoint()
    except Exception:
        if current_app and current_app.logger:
            current_app.logger.exception("Failed to load token endpoint")
        return None
    if logger:
        logger.info("Exchanging OAuth code for token")
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.entra.client_id,
        "client_secret": settings.entra.client_secret,
        "code": code,
        "redirect_uri": settings.entra.redirect_uri,
    }

    try:
        response = requests.post(token_endpoint, data=data, timeout=10)
        if not response.ok:
            if current_app and current_app.logger:
                current_app.logger.warning(
                    "Token endpoint error: %s", response.text
                )
            return None
        return response.json()
    except requests.RequestException:
        if current_app and current_app.logger:
            current_app.logger.exception("Token endpoint request failed")
        return None


def _safe_next_url(target: Optional[str]) -> Optional[str]:
    if not target:
        return None
    if target.startswith("/") and not target.startswith("//"):
        return target
    return None
