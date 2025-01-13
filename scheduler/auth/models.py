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
    active: bool = True
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user has valid authentication"""
        if not self.token or not self.token_expiry:
            return False
        return datetime.utcnow() < self.token_expiry
        
    @property
    def id(self) -> str:
        """Return username as id for compatibility with existing code"""
        return self.username
        
    @property
    def label(self) -> str:
        """Return display name as label for compatibility"""
        return self.display_name
        
    @property
    def addr(self) -> str:
        """Return email as addr for compatibility"""
        return self.email
