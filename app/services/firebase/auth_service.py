"""Firebase Admin authentication service."""

import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
import json
import os

logger = logging.getLogger(__name__)


class FirebaseService:
    """Service for Firebase Admin authentication and user management."""
    
    # Firebase token expiration
    CUSTOM_TOKEN_EXPIRATION_HOURS = 24
    
    def __init__(self, credentials_path: Optional[str] = None):
        """Initialize Firebase Admin SDK.
        
        Args:
            credentials_path: Path to Firebase credentials JSON file.
                            If None, looks for FIREBASE_CREDENTIALS_PATH env var
                            or uses default application credentials.
        """
        self._app = None
        self._auth = None
        self._initialized = False
        
        try:
            self.initialize(credentials_path)
        except Exception as e:
            logger.error(f"Failed to initialize Firebase service: {e}")
    
    def initialize(self, credentials_path: Optional[str] = None) -> bool:
        """Initialize Firebase Admin SDK with credentials.
        
        Args:
            credentials_path: Path to Firebase credentials JSON file
            
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            import firebase_admin
            from firebase_admin import credentials, auth
            
            # Determine credentials path
            if credentials_path is None:
                credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            
            if credentials_path and os.path.exists(credentials_path):
                # Initialize with credentials file
                cred = credentials.Certificate(credentials_path)
                self._app = firebase_admin.initialize_app(cred)
                logger.info(f"Firebase initialized with credentials: {credentials_path}")
            else:
                # Use default application credentials
                self._app = firebase_admin.initialize_app()
                logger.info("Firebase initialized with default credentials")
            
            self._auth = auth
            self._initialized = True
            logger.info("Firebase Admin SDK initialized successfully")
            return True
            
        except ImportError:
            logger.error("firebase-admin package not installed")
            return False
        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            return False
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify Firebase authentication token.
        
        Args:
            token: Firebase ID token or custom token
            
        Returns:
            Dictionary with decoded token data including:
            - uid: User ID
            - email: User email (if available)
            - email_verified: Email verification status
            - name: User display name (if available)
            - custom_claims: Custom claims (if set)
            Or None if token is invalid
            
        Raises:
            ValueError: If token is empty
        """
        try:
            if not token:
                raise ValueError("Token cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            # Verify the token
            decoded_token = self._auth.verify_id_token(token)
            
            logger.debug(f"Token verified for user: {decoded_token.get('uid')}")
            return decoded_token
            
        except ValueError as e:
            logger.error(f"Invalid token: {e}")
            raise
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return None
    
    def create_user(self, email: str, password: str,
                   display_name: Optional[str] = None) -> Optional[str]:
        """Create a new Firebase user.
        
        Args:
            email: User email address
            password: User password (minimum 6 characters)
            display_name: Optional display name for user
            
        Returns:
            User ID (uid), or None if creation failed
            
        Raises:
            ValueError: If email or password is invalid
        """
        try:
            if not email or "@" not in email:
                raise ValueError("Invalid email address")
            if not password or len(password) < 6:
                raise ValueError("Password must be at least 6 characters")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            # Create user
            user = self._auth.create_user(
                email=email,
                password=password,
                display_name=display_name
            )
            
            logger.info(f"User created successfully: {user.uid}")
            return user.uid
            
        except ValueError as e:
            logger.error(f"Invalid user data: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None
    
    def delete_user(self, uid: str) -> bool:
        """Delete a Firebase user.
        
        Args:
            uid: User ID to delete
            
        Returns:
            True if deletion successful, False otherwise
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            self._auth.delete_user(uid)
            
            logger.info(f"User deleted: {uid}")
            return True
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False
    
    def get_user(self, uid: str) -> Optional[Dict]:
        """Get user record by ID.
        
        Args:
            uid: User ID
            
        Returns:
            Dictionary with user data:
            - uid: User ID
            - email: Email address
            - email_verified: Whether email is verified
            - display_name: Display name (if set)
            - disabled: Whether user is disabled
            - metadata: Account creation/last sign-in times
            Or None if user not found
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            user = self._auth.get_user(uid)
            
            user_dict = {
                "uid": user.uid,
                "email": user.email,
                "email_verified": user.email_verified,
                "display_name": user.display_name,
                "disabled": user.disabled,
                "metadata": {
                    "creation_time": user.user_metadata.creation_timestamp,
                    "last_sign_in_time": user.user_metadata.last_sign_in_timestamp,
                },
                "custom_claims": user.custom_claims or {},
            }
            
            logger.debug(f"Retrieved user: {uid}")
            return user_dict
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user record by email address.
        
        Args:
            email: User email address
            
        Returns:
            User dictionary (same format as get_user), or None if not found
            
        Raises:
            ValueError: If email is invalid
        """
        try:
            if not email or "@" not in email:
                raise ValueError("Invalid email address")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            user = self._auth.get_user_by_email(email)
            
            user_dict = {
                "uid": user.uid,
                "email": user.email,
                "email_verified": user.email_verified,
                "display_name": user.display_name,
                "disabled": user.disabled,
                "metadata": {
                    "creation_time": user.user_metadata.creation_timestamp,
                    "last_sign_in_time": user.user_metadata.last_sign_in_timestamp,
                },
                "custom_claims": user.custom_claims or {},
            }
            
            logger.debug(f"Retrieved user by email: {email}")
            return user_dict
            
        except ValueError as e:
            logger.error(f"Invalid email: {e}")
            raise
        except Exception as e:
            logger.error(f"Error getting user by email: {e}")
            return None
    
    def create_custom_token(self, uid: str, additional_claims: Optional[Dict] = None) -> Optional[str]:
        """Create a custom Firebase token for API authentication.
        
        This token can be used to authenticate requests to the backend API
        without requiring Firebase client SDK.
        
        Args:
            uid: User ID
            additional_claims: Optional dictionary of custom claims to include
            
        Returns:
            Custom token string, or None if creation failed
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            # Create custom token with optional claims
            custom_token = self._auth.create_custom_token(
                uid,
                additional_claims=additional_claims or {}
            )
            
            logger.info(f"Custom token created for user: {uid}")
            return custom_token.decode() if isinstance(custom_token, bytes) else custom_token
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating custom token: {e}")
            return None
    
    def update_user(self, uid: str, **kwargs) -> Optional[Dict]:
        """Update user properties.
        
        Args:
            uid: User ID
            **kwargs: Properties to update:
                - email: New email address
                - password: New password
                - display_name: New display name
                - disabled: Disable/enable user (boolean)
                - email_verified: Mark email as verified (boolean)
                
        Returns:
            Updated user dictionary, or None if update failed
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            # Update user
            self._auth.update_user(uid, **kwargs)
            
            logger.info(f"User updated: {uid}")
            
            # Return updated user info
            return self.get_user(uid)
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            return None
    
    def set_custom_claims(self, uid: str, custom_claims: Dict) -> bool:
        """Set custom claims for a user (admin-only operation).
        
        Custom claims are useful for role-based access control (RBAC).
        
        Args:
            uid: User ID
            custom_claims: Dictionary of custom claims to set
                          (or None to unset claims)
                
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            self._auth.set_custom_user_claims(uid, custom_claims or {})
            
            logger.info(f"Custom claims set for user: {uid}")
            return True
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error setting custom claims: {e}")
            return False
    
    def revoke_tokens(self, uid: str) -> bool:
        """Revoke all tokens for a user (forces re-authentication).
        
        Args:
            uid: User ID
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValueError: If uid is empty
        """
        try:
            if not uid:
                raise ValueError("uid cannot be empty")
            
            if not self._initialized:
                raise RuntimeError("Firebase not initialized")
            
            self._auth.revoke_refresh_tokens(uid)
            
            logger.info(f"Tokens revoked for user: {uid}")
            return True
            
        except ValueError as e:
            logger.error(f"Invalid uid: {e}")
            raise
        except Exception as e:
            logger.error(f"Error revoking tokens: {e}")
            return False
    
    def is_initialized(self) -> bool:
        """Check if Firebase service is initialized.
        
        Returns:
            True if initialized successfully
        """
        return self._initialized
