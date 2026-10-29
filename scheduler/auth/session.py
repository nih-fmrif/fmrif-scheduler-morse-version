"""Session helpers for OAuth and test-only authentication flows."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, List, Optional

from flask import abort, current_app, g, request, session
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from scheduler import model
from scheduler.config import settings
from scheduler.logic import upsert_user

from .jwt_utils import extract_bearer_token, user_from_claims, verify_jwt
from .models import SessionUser
from .test_session_state import (
    clear_auth_test_session_pi_groups,
    merge_auth_test_session_pi_groups,
    set_auth_test_session_pi_groups,
)

_AUTH_TEST_SESSION_KEY = re.compile(r"^[a-z0-9]{1,6}$")
_AUTH_TEST_USER_ID_MAX = 20


@dataclass(frozen=True)
class ResolvedAuthTestProfile:
    username: str
    email: str
    display_name: str
    active: bool
    admin: bool
    groups: List[str]
    pi_groups: List[str]
    technologist: bool
    test_scanner_tech: bool


def _persist_user(user: SessionUser) -> SessionUser:
    """Ensure the user exists in the local database."""
    persisted = upsert_user(
        user.username,
        user.email,
        user.display_name,
        migrate_to_requested_id=True,
    )
    model.db.session.commit()
    user.username = persisted.id
    user.email = persisted.addr
    user.display_name = persisted.label
    return user


def _find_existing_user_by_email(email: str):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None
    return model.User.query.filter(
        func.lower(model.User.addr) == normalized_email
    ).first()


def _is_bearer_auto_provision_allowed(user: SessionUser) -> bool:
    if _find_existing_user_by_email(user.email) is not None:
        return True

    if not settings.entra.bearer_auto_provision_enabled:
        if current_app and current_app.logger:
            current_app.logger.warning(
                "Bearer auto-provision blocked for %s (disabled by policy)", user.email
            )
        return False

    allowed_domains = settings.entra.bearer_auto_provision_domains
    if allowed_domains:
        email_domain = user.email.rsplit("@", 1)[1].lower() if "@" in user.email else ""
        if email_domain not in allowed_domains:
            if current_app and current_app.logger:
                current_app.logger.warning(
                    "Bearer auto-provision blocked for %s (domain not allowed)",
                    user.email,
                )
            return False

    required_groups = settings.entra.bearer_auto_provision_groups
    if required_groups:
        claim_groups = {
            str(group).strip().lower()
            for group in (user.groups or [])
            if str(group).strip()
        }
        if not claim_groups.intersection(required_groups):
            if current_app and current_app.logger:
                current_app.logger.warning(
                    "Bearer auto-provision blocked for %s (group policy not met)",
                    user.email,
                )
            return False

    return True


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
    except (AttributeError, RuntimeError, TypeError):
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

    try:
        user = user_from_claims(claims)
    except ValueError as exc:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims invalid: %s", exc)
        return None

    if not _is_bearer_auto_provision_allowed(user):
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

    try:
        user = user_from_claims(claims)
    except ValueError as exc:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims invalid during login: %s", exc)
        return None

    if not _is_bearer_auto_provision_allowed(user):
        return None

    _persist_user(user)
    _store_session(user)
    g.user = user
    return user


def login_user_with_claims(claims: Dict) -> Optional[SessionUser]:
    """Create a session from already-validated JWT claims."""
    try:
        user = user_from_claims(claims)
    except ValueError as exc:
        if current_app and current_app.logger:
            current_app.logger.warning("JWT claims invalid during login: %s", exc)
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
    clear_auth_test_session_pi_groups()
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
        db_user = model.get(model.User, username)
        if db_user is not None:
            active = bool(db_user.active)
    except (SQLAlchemyError, RuntimeError):
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
    admin_group = model.get(model.Group, "admin")
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

    membership = model.get(model.GroupMember, ("admin", user_id))

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

    else:
        if membership is not None:
            model.db.session.delete(membership)

        # Admin role checks key off approved membership, not PI designation.
        # Keep any pre-existing admin PI row from seeded data untouched.


def _normalize_profile_groups(groups: List[str]) -> List[str]:
    normalized: List[str] = []
    for group in groups:
        group_id = str(group).strip()
        if not group_id:
            continue
        if group_id not in normalized:
            normalized.append(group_id)
    return normalized


def normalize_auth_test_session_key(raw: Optional[object]) -> str:
    value = str(raw or "").strip().lower()
    if value == "":
        return ""
    if not _AUTH_TEST_SESSION_KEY.fullmatch(value):
        raise ValueError("session_key must be 1-6 lowercase letters or digits")
    return value


def _scope_auth_test_username(username: str, session_key: str) -> str:
    base = username.strip().lower()
    if session_key == "":
        return base
    suffix = f"-{session_key}"
    if len(base) + len(suffix) > _AUTH_TEST_USER_ID_MAX:
        base = base[: _AUTH_TEST_USER_ID_MAX - len(suffix)].rstrip("-")
    return f"{base}{suffix}"


def _scope_auth_test_email(email: str, session_key: str) -> str:
    base = str(email).strip().lower()
    if session_key == "" or "@" not in base:
        return base
    local_part, domain = base.split("@", 1)
    return f"{local_part}+{session_key}@{domain}"


def resolve_auth_test_profile(
    profile_name: str, *, session_key: str = ""
) -> Optional[ResolvedAuthTestProfile]:
    profile = settings.auth_test.profiles.get(profile_name)
    if profile is None:
        return None
    username = _scope_auth_test_username(profile.username, session_key)
    display_name = profile.display_name.strip() or username
    return ResolvedAuthTestProfile(
        username=username,
        email=_scope_auth_test_email(profile.email, session_key),
        display_name=display_name,
        active=bool(profile.active),
        admin=bool(profile.admin),
        groups=_normalize_profile_groups(list(profile.groups)),
        pi_groups=_normalize_profile_groups(list(profile.pi_groups)),
        technologist=bool(profile.technologist),
        test_scanner_tech=bool(profile.test_scanner_tech),
    )


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
    group = model.get(model.Group, group_id)
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


def _set_profile_group_membership(
    user_id: str, group_id: str, enabled: bool, *, pi: bool = False
) -> None:
    if enabled:
        _ensure_auth_test_group(group_id)

    membership = model.get(model.GroupMember, (group_id, user_id))
    primary = model.get(model.PrimaryGroupMember, (group_id, user_id))

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
        if pi:
            current_primary = model.PrimaryGroupMember.query.filter_by(
                group=group_id
            ).first()
            if current_primary is not None and current_primary.user != user_id:
                model.execute(
                    "delete from primarygroupmember where deptcode = :group_id",
                    {"group_id": group_id},
                )
                model.db.session.flush()
            if primary is None:
                model.db.session.add(
                    model.PrimaryGroupMember(group=group_id, user=user_id)
                )
        elif primary is not None:
            model.db.session.delete(primary)
        return

    if membership is not None:
        model.db.session.delete(membership)
    if primary is not None:
        model.db.session.delete(primary)


def _set_technologist_status(user_id: str, enabled: bool) -> None:
    record = model.get(model.Technologist, user_id)
    if enabled:
        if record is None:
            model.db.session.add(
                model.Technologist(
                    user=user_id,
                    applied_on=func.now(),
                    approved_on=func.now(),
                    email_status="none",
                )
            )
        else:
            if record.applied_on is None:
                record.applied_on = func.now()
            if record.approved_on is None:
                record.approved_on = func.now()
            if (record.email_status or "").strip() == "":
                record.email_status = "none"
            model.db.session.add(record)
        return
    # Do not delete existing records when a profile is not technologist.
    # This keeps test-session profile switching from erasing legitimate approvals.


def _ensure_auth_test_device(device_id: str) -> None:
    device = model.get(model.Device, device_id)
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
    permission = model.get(model.UserDevice, (user_id, scanner_id))

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

    # Keep existing membership rows intact across profile switches.


def login_test_user(
    profile_name: str, *, session_key: str = ""
) -> Optional[SessionUser]:
    """Create a mock authenticated session for integration tests."""
    profile = resolve_auth_test_profile(profile_name, session_key=session_key)
    if profile is None:
        return None

    username = profile.username
    email = profile.email
    display_name = profile.display_name
    profile_groups = profile.groups
    profile_pi_groups = profile.pi_groups
    persist_primary_memberships = session_key == ""

    db_user = upsert_user(username, email, display_name)
    db_user.active = profile.active
    model.db.session.add(db_user)
    for group_id in profile_groups:
        if group_id.lower() == "admin":
            continue
        _set_profile_group_membership(
            username,
            group_id,
            True,
            pi=persist_primary_memberships and group_id in profile_pi_groups,
        )
    for group_id in profile_pi_groups:
        if group_id.lower() == "admin" or group_id in profile_groups:
            continue
        _set_profile_group_membership(
            username,
            group_id,
            True,
            pi=persist_primary_memberships,
        )
    _set_admin_membership(username, profile.admin)
    _set_technologist_status(username, profile.technologist)
    _set_test_scanner_tech_permission(username, profile.test_scanner_tech)
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
    set_auth_test_session_pi_groups(username, profile_pi_groups)
    g.user = user
    return user


def apply_test_group_pi_memberships(
    user_id: str,
    group_ids: List[str],
    *,
    persist_primary_memberships: bool = True,
) -> None:
    normalized_groups = _normalize_profile_groups(list(group_ids))
    for group_id in normalized_groups:
        if group_id.lower() == "admin":
            continue
        _set_profile_group_membership(
            user_id,
            group_id,
            True,
            pi=persist_primary_memberships,
        )
    model.db.session.commit()
    merge_auth_test_session_pi_groups(user_id, normalized_groups)


def reset_test_auth_profile_state(user_id: str) -> None:
    (
        model.PrimaryGroupMember.query.filter(
            model.PrimaryGroupMember.user == user_id
        ).delete(synchronize_session=False)
    )
    (
        model.GroupMember.query.filter(model.GroupMember.user == user_id).delete(
            synchronize_session=False
        )
    )
    (
        model.Technologist.query.filter(model.Technologist.user == user_id).delete(
            synchronize_session=False
        )
    )
    (
        model.UserDevice.query.filter(model.UserDevice.user == user_id).delete(
            synchronize_session=False
        )
    )
    model.db.session.commit()
    set_auth_test_session_pi_groups(user_id, [])


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
