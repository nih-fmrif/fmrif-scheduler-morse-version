"""Session helpers for OAuth and test-only authentication flows."""

import re
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, List, Optional

from flask import abort, current_app, g, request, session

from scheduler import model
from scheduler.config import settings
from scheduler.logic import upsert_user

from .jwt_utils import extract_bearer_token, user_from_claims, verify_jwt
from .models import SessionUser


def _persist_user(user: SessionUser) -> SessionUser:
    """Ensure the user exists in the local database."""
    persisted = upsert_user(user.username, user.email, user.display_name)
    model.db.session.commit()
    user.username = persisted.id
    user.email = persisted.addr
    user.display_name = persisted.label
    return user


def _rotate_session_identifier() -> None:
    """Best-effort session id rotation to reduce fixation risk after login."""
    interface = getattr(current_app, "session_interface", None)
    generate_sid = getattr(interface, "_generate_sid", None)
    current_sid = getattr(session, "sid", None)
    if current_sid is None or not callable(generate_sid):
        return
    try:
        session.sid = generate_sid()
        session.modified = True
    except Exception:
        if current_app and current_app.logger:
            current_app.logger.exception("Failed to rotate session identifier")


def _store_session(user: SessionUser) -> None:
    """Store the authenticated user in the Flask session."""
    _rotate_session_identifier()
    session.clear()
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
            current_app.logger.warning(
                "JWT verification failed during login: %s", error
            )
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

    active = True
    try:
        db_user = model.User.query.get(username)
        if db_user is not None:
            active = bool(db_user.active)
    except Exception:
        if current_app and current_app.logger:
            current_app.logger.exception(
                "Failed to load active flag for session user %s", username
            )
        # Fail closed when active-state lookup cannot be trusted.
        active = False

    return SessionUser(
        username=username,
        email=email,
        display_name=display_name,
        groups=groups,
        active=active,
    )


def _set_admin_membership(user_id: str, enabled: bool) -> None:
    """Set or remove admin membership for a user."""
    admin_group = model.Group.query.get("admin")
    if enabled and admin_group is None:
        admin_group = model.Group(
            id="admin",
            label="admin",
            description="Admin",
            active=True,
        )
        model.db.session.add(admin_group)

    if admin_group is None:
        return

    membership = model.GroupMember.query.get(("admin", user_id))
    primary = model.PrimaryGroupMember.query.get(("admin", user_id))

    if enabled:
        approved_at = datetime.now(timezone.utc)
        if membership is None:
            membership = model.GroupMember(
                group="admin", user=user_id, approved=approved_at
            )
            model.db.session.add(membership)
        elif membership.approved is None:
            membership.approved = approved_at
            model.db.session.add(membership)

        if primary is None:
            model.db.session.add(model.PrimaryGroupMember(group="admin", user=user_id))
    else:
        if membership is not None:
            model.db.session.delete(membership)
        if primary is not None:
            model.db.session.delete(primary)


def _normalize_profile_groups(groups: List[str]) -> List[str]:
    normalized: List[str] = []
    for group in groups:
        group_id = str(group).strip()
        if not group_id:
            continue
        if group_id not in normalized:
            normalized.append(group_id)
    return normalized


def _parse_auth_test_seed_groups(raw: str) -> List[str]:
    """Parse comma-separated auth-test seed group ids from environment settings."""
    groups: List[str] = []
    for token in (raw or "").split(","):
        value = token.strip().upper()
        if not value:
            continue
        if not re.fullmatch(r"[A-Z0-9_-]{1,10}", value):
            if current_app and current_app.logger:
                current_app.logger.warning(
                    "Ignoring invalid AUTH_TEST__SEED_GROUPS entry: %r", token
                )
            continue
        if value not in groups:
            groups.append(value)

    if "DEV" not in groups:
        groups.insert(0, "DEV")
    return groups


def _ensure_auth_test_group(group_id: str) -> None:
    group = model.Group.query.get(group_id)
    if group is None:
        group = model.Group(id=group_id)

    if not group.label:
        group.label = group_id
    if not group.description:
        group.description = f"Auth test group {group_id}"
    if not group.color:
        group.color = "#225588"

    group.active = True
    group.has_membership = True
    model.db.session.add(group)


def _set_profile_group_membership(user_id: str, group_id: str, enabled: bool) -> None:
    if enabled:
        _ensure_auth_test_group(group_id)

    membership = model.GroupMember.query.get((group_id, user_id))
    primary = model.PrimaryGroupMember.query.get((group_id, user_id))

    if enabled:
        approved_at = datetime.now(timezone.utc)
        if membership is None:
            membership = model.GroupMember(
                group=group_id,
                user=user_id,
                approved=approved_at,
            )
            model.db.session.add(membership)
        elif membership.approved is None:
            membership.approved = approved_at
            model.db.session.add(membership)
        return

    if membership is not None:
        model.db.session.delete(membership)
    if primary is not None:
        model.db.session.delete(primary)


def _set_technologist_status(user_id: str, enabled: bool) -> None:
    record = model.Technologist.query.get(user_id)
    if enabled:
        if record is None:
            model.db.session.add(model.Technologist(user=user_id))
        return
    if record is not None:
        model.db.session.delete(record)


def _ensure_auth_test_device(device_id: str) -> None:
    device = model.Device.query.get(device_id)
    if device is None:
        device = model.Device(id=device_id)

    if not device.label:
        device.label = "Test Scanner"
    if not device.description:
        device.description = "Auth test scanner"
    if not device.addr:
        device.addr = "test-scanner@example.com"

    device.active = True
    model.db.session.add(device)


def _set_test_scanner_tech_permission(user_id: str, enabled: bool) -> None:
    scanner_id = "TEST"
    permission = model.UserDevice.query.get((user_id, scanner_id))

    if enabled:
        _ensure_auth_test_device(scanner_id)
        if permission is None:
            permission = model.UserDevice(
                user=user_id,
                device=scanner_id,
                templates=False,
                slot=False,
                tech=True,
                medical=False,
                training=False,
            )
        else:
            permission.templates = False
            permission.slot = False
            permission.tech = True
            permission.medical = False
            permission.training = False
        model.db.session.add(permission)
        return

    if permission is not None:
        model.db.session.delete(permission)


def _ensure_joinable_seed_group_for_user(
    user_id: str, profile_groups: List[str]
) -> None:
    seed_groups = _parse_auth_test_seed_groups(settings.auth_test.seed_groups)
    for group_id in seed_groups:
        _ensure_auth_test_group(group_id)

    profile_group_ids = {group.strip().upper() for group in profile_groups if group}
    joinable_seed = next(
        (group_id for group_id in seed_groups if group_id not in profile_group_ids),
        None,
    )
    if joinable_seed is None:
        return

    membership = model.GroupMember.query.get((joinable_seed, user_id))
    if membership is not None:
        model.db.session.delete(membership)

    primary = model.PrimaryGroupMember.query.get((joinable_seed, user_id))
    if primary is not None:
        model.db.session.delete(primary)


def login_test_user(profile_name: str) -> Optional[SessionUser]:
    """Create a mock authenticated session for integration tests."""
    profile = settings.auth_test.profiles.get(profile_name)
    if profile is None:
        return None

    username = profile.username.strip().lower()
    email = str(profile.email).strip().lower()
    display_name = profile.display_name.strip() or username
    profile_groups = _normalize_profile_groups(list(profile.groups))

    db_user = upsert_user(username, email, display_name)
    db_user.active = bool(profile.active)
    model.db.session.add(db_user)
    for group_id in profile_groups:
        if group_id.lower() == "admin":
            continue
        _set_profile_group_membership(username, group_id, True)
    _set_admin_membership(username, bool(profile.admin))
    _set_technologist_status(username, bool(profile.technologist))
    _set_test_scanner_tech_permission(username, bool(profile.test_scanner_tech))
    _ensure_joinable_seed_group_for_user(username, profile_groups)
    model.db.session.commit()

    user = SessionUser(
        username=username,
        email=email,
        display_name=display_name,
        groups=profile_groups,
        active=bool(db_user.active),
    )
    _store_session(user)
    g.user = user
    return user


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
