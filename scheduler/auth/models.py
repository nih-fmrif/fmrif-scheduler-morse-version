"""Models for authentication"""
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

@dataclass
class LDAPUser:
    """Represents an authenticated LDAP user"""
    username: str
    display_name: str
    email: str
    groups: List[str]
    token: Optional[str] = None
    token_expiry: Optional[datetime] = None
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user has valid authentication"""
        if not self.token or not self.token_expiry:
            return False
        return datetime.utcnow() < self.token_expiry