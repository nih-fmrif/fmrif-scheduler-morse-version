"""Session management for authentication"""
from typing import Optional
from datetime import datetime
from flask import session, g
from .models import LDAPUser
from .token_store import TokenStore
from .ldap import LDAPClient
from ..logic import upsert_user  # Import the existing user creation function
from ..model import db

def login_user(user: LDAPUser) -> None:
    """Log in a user by creating session and token"""
    # Create/update local user record
    local_user = upsert_user(
        user.username,
        user.email, 
        user.display_name
    )
    db.session.commit()
    
    # Store token
    token = TokenStore.create_token(user.username, user.token_expiry)
    user.token = token
    
    # Update session
    session["user_name"] = user.username
    session["token"] = token
    
    # Store user in request context 
    g.user = local_user

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
    token = session.get("token")
    if not token:
        return None
        
    user_id = TokenStore.validate_token(token)
    if not user_id:
        logout_user()
        return None
    
    # Re-fetch user details from LDAP
    ldap = LDAPClient()
    conn = ldap._get_connection()
    if not conn.bind():
        return None
        
    conn.search(
        ldap.config.base_dn,
        f"(&{ldap.config.user_search_filter}(uid={user_id}))",
        attributes=['displayName', 'mail', 'uid']
    )
    
    if not conn.entries:
        return None
        
    user_entry = conn.entries[0]
    groups = ldap._get_user_groups(user_id)
    
    return LDAPUser(
        username=user_id,
        display_name=str(user_entry.displayName),
        email=str(user_entry.mail),
        groups=groups,
        token=token,
        token_expiry=datetime.utcnow()  # We'll update this when extending the session
    )