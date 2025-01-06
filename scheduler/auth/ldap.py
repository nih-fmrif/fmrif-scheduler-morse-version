"""LDAP authentication implementation"""
from typing import Optional, Tuple
import ldap3
from datetime import datetime, timedelta
import secrets
from flask import current_app

from .models import LDAPUser
from ..config import settings

class LDAPClient:
    """Client for LDAP authentication and user management"""
    
    def __init__(self):
        """Initialize LDAP client with config settings"""
        self.config = settings.ldap
        
    def _get_connection(self, user_dn: Optional[str] = None, password: Optional[str] = None) -> ldap3.Connection:
        """Get LDAP connection using either bind DN or user credentials"""
        server = ldap3.Server(
            self.config.host,
            port=self.config.port,
            use_ssl=self.config.use_ssl
        )
        
        if user_dn and password:
            return ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                authentication=ldap3.SIMPLE
            )
        
        return ldap3.Connection(
            server,
            user=self.config.bind_dn,
            password=self.config.bind_password,
            authentication=ldap3.SIMPLE
        )

    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[LDAPUser]]:
        """Authenticate user against LDAP server"""
        try:
            # Format user DN from template
            user_dn = self.config.user_dn_template.format(username=username)
            
            # Try to bind with user credentials
            conn = self._get_connection(user_dn, password)
            if not conn.bind():
                return False, None
                
            # Search for user details
            conn.search(
                self.config.base_dn,
                f"(&{self.config.user_search_filter}(uid={username}))",
                attributes=['displayName', 'mail', 'uid']
            )
            
            if not conn.entries:
                return False, None
                
            user_entry = conn.entries[0]
            
            # Get user's groups
            groups = self._get_user_groups(username)
            
            # Generate authentication token
            token = secrets.token_urlsafe(32)
            expiry = datetime.utcnow() + timedelta(seconds=self.config.token_lifetime)
            
            user = LDAPUser(
                username=username,
                display_name=str(user_entry.displayName),
                email=str(user_entry.mail),
                groups=groups,
                token=token,
                token_expiry=expiry
            )
            
            return True, user
            
        except ldap3.core.exceptions.LDAPException as e:
            current_app.logger.error(f"LDAP authentication error: {str(e)}")
            return False, None
            
    def _get_user_groups(self, username: str) -> List[str]:
        """Get list of groups user belongs to"""
        conn = self._get_connection()
        if not conn.bind():
            return []
            
        conn.search(
            self.config.group_dn,
            f"(&{self.config.group_search_filter}(uniqueMember=uid={username},{self.config.base_dn}))",
            attributes=['cn']
        )
        
        return [str(entry.cn) for entry in conn.entries]

    def validate_token(self, token: str) -> Optional[LDAPUser]:
        """Validate an authentication token"""
        # This would typically check against a token store
        # For now, we'll need to implement token storage
        return None