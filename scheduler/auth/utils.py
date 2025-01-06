"""Authentication utility functions"""
from functools import wraps
from flask import g, current_app, abort
from typing import Optional, Callable

from .models import LDAPUser
from .ldap import LDAPClient

def get_current_user() -> Optional[LDAPUser]:
    """Get currently authenticated user"""
    if hasattr(g, 'user'):
        return g.user
    return None

def login_required(f: Callable) -> Callable:
    """Decorator to require login for views"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if user is None or not user.is_authenticated:
            abort(403, "Access denied: Authentication required")
        return f(*args, **kwargs)
    return decorated_function

def has_role(role: str) -> bool:
    """Check if current user has specified role"""
    user = get_current_user()
    if not user:
        return False
    return role in user.groups