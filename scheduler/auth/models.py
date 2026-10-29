"""Models for authentication"""

from dataclasses import dataclass, field
from typing import List, Mapping, Optional


@dataclass
class SessionUser:
    """Represents an authenticated user built from JWT claims."""

    username: str
    email: str
    display_name: str = ""
    groups: List[str] = field(default_factory=list)
    claims: Optional[Mapping[str, object]] = None
    active: bool = True

    @property
    def id(self) -> str:
        """Return username as id for compatibility with existing code"""
        return self.username

    @property
    def label(self) -> str:
        """Return display name as label for compatibility"""
        return self.display_name or self.username

    @property
    def addr(self) -> str:
        """Return email as addr for compatibility"""
        return self.email
