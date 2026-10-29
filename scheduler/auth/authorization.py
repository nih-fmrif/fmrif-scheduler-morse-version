"""Authorization helpers for JWT-authenticated users."""

from functools import wraps
from typing import Optional

from flask import abort, g
from sqlalchemy import select

from scheduler import logic, model


def get_user_by_email(email: str) -> Optional[model.User]:
    """Fetch a user by email address."""
    if not email:
        return None
    statement = select(model.User).where(model.User.addr == email).limit(1)
    return model.db.session.execute(statement).scalars().first()


def ensure_user(email: str, username: str, display_name: str) -> model.User:
    """Ensure a user exists in the database."""
    existing = get_user_by_email(email)
    if existing:
        return existing
    # use email local-part as id if not present
    user_id = username or email.split("@")[0]
    user = model.User(
        id=user_id, addr=email, label=display_name or user_id, active=True
    )
    model.db.session.add(user)
    model.db.session.commit()
    return user


def require_permission(permission_name: str):
    """Decorator to enforce simple permission checks (admin for now)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not getattr(g, "user", None):
                abort(401, "Access denied: Authentication required")

            db_user = get_user_by_email(g.user.email)
            if not db_user:
                abort(403, f"User {g.user.email} not found")

            if permission_name == "admin" and not logic.is_admin(db_user):
                abort(403, "Admin permission required")

            # Additional permission hooks can be added here.
            return fn(*args, **kwargs)

        return wrapper

    return decorator
