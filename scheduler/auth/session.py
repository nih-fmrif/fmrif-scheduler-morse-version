# scheduler/auth/session.py

from datetime import datetime, timedelta
from typing import Optional

from flask import current_app, g, session

from scheduler.config import settings

from ..logic import upsert_user
from ..model import db
from .ldap import LDAPClient
from .models import LDAPUser
from .token_store import TokenStore


def get_ldap_client() -> LDAPClient:
    """Get LDAP client from application context"""
    if not hasattr(current_app, "ldap_client"):
        current_app.ldap_client = LDAPClient()
    return current_app.ldap_client


def login_user(user: LDAPUser) -> None:
    """Log in a user by creating session and token"""
    # Create/update local user record
    upsert_user(user.username, user.email, user.display_name)
    db.session.commit()

    # Store token with LDAP-configured expiry
    token_expiry = datetime.utcnow() + timedelta(seconds=settings.ldap.token_lifetime)
    token = TokenStore.create_token(user.username, token_expiry)
    user.token = token
    user.token_expiry = token_expiry

    # Make session permanent and set its expiry
    session.permanent = True

    # Update session with all user info
    session["user_name"] = user.username
    session["display_name"] = user.display_name
    session["email"] = user.email
    session["groups"] = user.groups
    session["token"] = token

    # Store user in request context
    g.user = user


def logout_user() -> None:
    """Log out current user"""
    if "token" in session:
        TokenStore.delete_token(session["token"])

    session.pop("user_name", None)
    session.pop("token", None)

    if hasattr(g, "user"):
        delattr(g, "user")


def get_user_from_session() -> Optional[LDAPUser]:
    """Get user from current session if valid"""
    try:
        token = session.get("token")
        if not token:
            return None

        user_id = TokenStore.validate_token(token)
        if not user_id:
            logout_user()
            return None

        ldap = get_ldap_client()
        conn = ldap._get_connection()
        if not conn:
            current_app.logger.error("Failed to get LDAP connection")
            logout_user()
            return None

        conn.search(
            ldap.config.base_dn,
            f"(&{ldap.config.user_search_filter}(uid={user_id}))",
            attributes=["displayName", "mail", "uid"],
        )

        if not conn.entries:
            logout_user()
            return None

        user_entry = conn.entries[0]
        groups = ldap._get_user_groups(user_id)

        return LDAPUser(
            username=user_id,
            display_name=str(user_entry.displayName),
            email=str(user_entry.mail),
            groups=groups,
            token=token,
            token_expiry=datetime.utcnow()
            + timedelta(seconds=ldap.config.token_lifetime),
        )

    except Exception as e:
        current_app.logger.error(f"Error during session validation: {str(e)}")
        logout_user()
        return None
