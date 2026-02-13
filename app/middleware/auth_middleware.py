"""
Firebase token verification middleware.
Only imports firebase_admin when actually needed (not in local dev mode).
"""

from typing import Optional

from app.utils.exceptions import AuthenticationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FirebaseTokenVerifier:
    """Verifies Firebase ID tokens. Only used when Firebase is configured."""

    def __init__(self, credentials_path: str) -> None:
        self.credentials_path = credentials_path
        self._initialized = False

    def initialize(self) -> None:
        """Initialize Firebase app if not already initialized."""
        if self._initialized:
            return

        try:
            import firebase_admin
            from firebase_admin import credentials

            if not firebase_admin._apps:
                cred = credentials.Certificate(self.credentials_path)
                firebase_admin.initialize_app(cred)
            self._initialized = True
            logger.info("Firebase initialized successfully")
        except ImportError:
            logger.error("firebase_admin not installed")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {str(e)}")
            raise

    def verify_token(self, token: str) -> dict:
        """Verify Firebase ID token and return decoded claims."""
        if not self._initialized:
            self.initialize()

        try:
            from firebase_admin import auth
            decoded_token = auth.verify_id_token(token)
            return decoded_token
        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            raise AuthenticationError(
                message="Token verification failed",
                details={"error": "VERIFICATION_FAILED"},
            ) from e

    def get_user_uid(self, token: str) -> str:
        """Extract user UID from token."""
        decoded_token = self.verify_token(token)
        return decoded_token.get("uid")
