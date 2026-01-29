"""Token storage and management"""

import secrets
from datetime import datetime
from typing import Optional

from ..model import db


class TokenStore:
    """Manages authentication tokens in database"""

    @staticmethod
    def create_token(user_id: str, expiry: datetime) -> str:
        """Create and store new token"""
        token = secrets.token_urlsafe(32)

        # Delete any existing tokens for user
        db.session.execute(
            "DELETE FROM reset_tokens WHERE for_user = :user", {"user": user_id}
        )

        # Store new token
        db.session.execute(
            "INSERT INTO reset_tokens (token, for_user, issued) VALUES (:token, :user, :issued)",
            {"token": token, "user": user_id, "issued": expiry},
        )
        db.session.commit()

        return token

    @staticmethod
    def validate_token(token: str) -> Optional[str]:
        """Validate token and return user_id if valid"""
        result = db.session.execute(
            """SELECT for_user, issued FROM reset_tokens
               WHERE token = :token AND issued > CURRENT_TIMESTAMP""",
            {"token": token},
        ).fetchone()

        if result:
            return result[0]
        return None

    @staticmethod
    def delete_token(token: str) -> None:
        """Delete a token"""
        db.session.execute(
            "DELETE FROM reset_tokens WHERE token = :token", {"token": token}
        )
        db.session.commit()
