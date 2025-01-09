# scheduler/auth/session.py

from typing import Optional
from datetime import datetime
from flask import session, g, current_app
from .models import LDAPUser
from .token_store import TokenStore
from .ldap import LDAPClient
from ..logic import upsert_user
from ..model import db
from datetime import datetime, timedelta  # Add timedelta import
from flask import session, g, current_app, redirect, url_for

# Global LDAP client instance
_ldap_client = None

def get_ldap_client() -> LDAPClient:
    """Get or create LDAP client instance"""
    global _ldap_client
    if _ldap_client is None:
        _ldap_client = LDAPClient()
    return _ldap_client

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
        
        try:
            # Get LDAP client
            ldap = get_ldap_client()
            
            # Re-fetch user details from LDAP
            conn = ldap._get_connection()
            if not conn:
                current_app.logger.error("Failed to get LDAP connection")
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
                token_expiry=datetime.utcnow() + timedelta(seconds=3600)  # Extend session
            )
            
        except Exception as e:
            current_app.logger.error(f"LDAP error: {str(e)}")
            # Return cached user info to prevent logout
            return LDAPUser(
                username=user_id,
                display_name=session.get("display_name", user_id),
                email=session.get("email", ""),
                groups=session.get("groups", []),
                token=token,
                token_expiry=datetime.utcnow() + timedelta(seconds=3600)
            )
            
    except Exception as e:
        current_app.logger.error(f"Session error: {str(e)}")
        return None
