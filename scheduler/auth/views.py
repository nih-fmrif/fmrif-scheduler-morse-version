"""Authentication views"""

import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from scheduler import model
from scheduler.config import settings
from scheduler.logic import CsrfOnlyForm

from .jwt_utils import extract_bearer_token, verify_jwt
from .oidc import get_authorization_endpoint, get_token_endpoint
from .pkce import code_challenge_s256, generate_code_verifier
from .session import (
    apply_test_group_pi_memberships,
    get_user_from_session,
    login_test_user,
    login_user_with_claims,
    login_user_with_token,
    logout_user,
    normalize_auth_test_session_key,
    reset_test_auth_profile_state,
    resolve_auth_test_profile,
)

# Create blueprint
auth = Blueprint("auth", __name__)

OAUTH_STATE_TTL_SECONDS = 10 * 60
_AUTH_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_AUTH_RATE_LIMIT_LOCK = Lock()


def _is_auth_rate_limited(scope: str) -> bool:
    if not settings.security.auth_rate_limit_enabled:
        return False

    window = max(1, settings.security.auth_rate_limit_window_seconds)
    max_requests = max(1, settings.security.auth_rate_limit_max_requests)
    client = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    client_id = client.split(",", 1)[0].strip().lower() or "unknown"
    key = f"{scope}:{client_id}"
    now = time.time()
    cutoff = now - window

    with _AUTH_RATE_LIMIT_LOCK:
        bucket = _AUTH_RATE_LIMIT_BUCKETS[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            return True
        bucket.append(now)
    return False


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
            logger.warning("OAuth callback error: %s", error)
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

    token_response = _exchange_code_for_token(code, oauth_state.get("code_verifier"))
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
                "OAuth token missing preferred_username claim (available_claims=%s, has_preferred_username=%s)",
                sorted(claims.keys()),
                bool(claims.get("preferred_username")),
            )
        flash("Login failed. Missing preferred_username claim.", "error")
        return redirect(url_for("auth.login"))
    if logger:
        logger.info("OAuth login succeeded")

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
    code_verifier = generate_code_verifier()
    code_challenge = code_challenge_s256(code_verifier)
    state, nonce = _create_oauth_state(next_url, code_verifier)
    if not state or not nonce:
        if logger:
            logger.error("OAuth start failed: unable to persist state")
        flash("Login unavailable. Please try again later.", "error")
        return redirect(url_for("auth.login"))

    try:
        auth_endpoint = get_authorization_endpoint()
    except (ValueError, requests.RequestException):
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
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return redirect(f"{auth_endpoint}?{urlencode(params)}")


@auth.route("/session", methods=["POST"])
def establish_session():
    """Create a server session from a validated JWT bearer token."""
    if _is_auth_rate_limited("session"):
        return jsonify({"error": "Too many authentication attempts"}), 429

    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        return jsonify({"error": "Missing bearer token"}), 401

    user = login_user_with_token(token)
    if not user:
        return jsonify({"error": "Invalid or expired token"}), 401

    return jsonify({"email": user.email, "username": user.username})


@auth.route("/test/session", methods=["POST", "DELETE"])
def establish_test_session():
    """Create or clear a mock session for integration test suites.

    Security note: this endpoint can mint privileged mock sessions and must never
    be enabled in production. Exploitation requires all of the following:
    1. AUTH_TEST__ENABLED is true in a deployed environment.
    2. The shared secret is known or guessable by the attacker.
    3. The attacker can reach this route and send crafted profile payloads.
    """
    if _is_auth_rate_limited("test-session"):
        return jsonify({"error": "Too many authentication attempts"}), 429

    if not settings.auth_test.enabled:
        return jsonify({"error": "Not found"}), 404

    provided_secret = request.headers.get("X-Test-Auth-Secret", "")
    expected_secret = settings.auth_test.shared_secret
    if not provided_secret or not hmac.compare_digest(provided_secret, expected_secret):
        return jsonify({"error": "Forbidden"}), 403

    if request.method == "DELETE":
        logout_user()
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    profile = str(payload.get("profile") or "admin")
    try:
        session_key = normalize_auth_test_session_key(payload.get("session_key"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if session_key == "":
        return jsonify({"error": "session_key is required for auth test sessions"}), 400
    profile_config = resolve_auth_test_profile(profile, session_key=session_key)
    if profile_config is None:
        return jsonify({"error": f"Unknown test auth profile: {profile}"}), 400

    raw_reset_value = payload.get("reset_profile_state")
    if raw_reset_value is None:
        reset_profile_state = False
    elif isinstance(raw_reset_value, bool):
        reset_profile_state = raw_reset_value
    else:
        return jsonify({"error": "reset_profile_state must be a boolean"}), 400

    if reset_profile_state:
        target_user = profile_config.username
        try:
            reset_test_auth_profile_state(target_user)
        except SQLAlchemyError:
            model.db.session.rollback()
            if current_app and current_app.logger:
                current_app.logger.exception(
                    "Failed to reset auth-test profile state during test auth session setup"
                )
            return jsonify({"error": "Unable to reset test session state"}), 500

    try:
        user = login_test_user(profile, session_key=session_key)
    except SQLAlchemyError:
        model.db.session.rollback()
        if current_app and current_app.logger:
            current_app.logger.exception("Failed to establish test auth session")
        return jsonify({"error": "Unable to establish test session"}), 500
    if not user:
        return jsonify({"error": f"Unknown test auth profile: {profile}"}), 400

    raw_group_pi_groups = payload.get("group_pi_groups")
    if raw_group_pi_groups is not None:
        if isinstance(raw_group_pi_groups, str):
            group_pi_groups = [raw_group_pi_groups]
        elif isinstance(raw_group_pi_groups, list):
            group_pi_groups = [str(group_id) for group_id in raw_group_pi_groups]
        else:
            return jsonify({"error": "group_pi_groups must be a string or list"}), 400
        try:
            apply_test_group_pi_memberships(
                user.username,
                group_pi_groups,
                persist_primary_memberships=False,
            )
        except SQLAlchemyError:
            model.db.session.rollback()
            if current_app and current_app.logger:
                current_app.logger.exception(
                    "Failed to apply group_pi_groups during test auth session setup"
                )
            return jsonify(
                {"error": "Unable to apply test session group_pi_groups"}
            ), 500

    return jsonify(
        {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "active": user.active,
        }
    )


@auth.route("/logout", methods=["POST"])
def logout():
    """Handle user logout"""
    form = CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "Invalid logout request")
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
    redirect_next: Optional[str], code_verifier: str
) -> tuple[Optional[str], Optional[str]]:
    logger = current_app.logger if current_app else None
    for _ in range(3):
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        record = model.OAuthState(
            state=state,
            nonce=nonce,
            redirect_next=redirect_next,
            code_verifier=code_verifier,
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
            "code_verifier": record.code_verifier,
        }
        model.db.session.delete(record)
        model.db.session.commit()
        return payload
    except SQLAlchemyError:
        model.db.session.rollback()
        if logger:
            logger.exception("Failed to consume OAuth state")
        return None


def _exchange_code_for_token(code: str, code_verifier: Optional[str]) -> Optional[dict]:
    logger = current_app.logger if current_app else None
    if not code_verifier:
        if logger:
            logger.warning("OAuth token exchange blocked: missing code_verifier")
        return None
    try:
        token_endpoint = get_token_endpoint()
    except (ValueError, requests.RequestException):
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
        "code_verifier": code_verifier,
    }

    try:
        response = requests.post(token_endpoint, data=data, timeout=10)
        if not response.ok:
            if current_app and current_app.logger:
                current_app.logger.warning(
                    "Token endpoint error (status=%s)", response.status_code
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
