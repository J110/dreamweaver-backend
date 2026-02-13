"""Custom exceptions for DreamWeaver backend."""

from typing import Any, Dict, Optional


class DreamWeaverException(Exception):
    """Base exception for DreamWeaver application."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize DreamWeaverException.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code.
            error_code: Machine-readable error code.
            details: Additional error details.
        """
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)


class ContentGenerationError(DreamWeaverException):
    """Raised when content generation fails."""

    def __init__(
        self,
        message: str = "Failed to generate content",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ContentGenerationError."""
        super().__init__(
            message=message,
            status_code=500,
            error_code="CONTENT_GENERATION_ERROR",
            details=details,
        )


class TTSError(DreamWeaverException):
    """Raised when text-to-speech conversion fails."""

    def __init__(
        self,
        message: str = "Text-to-speech conversion failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize TTSError."""
        super().__init__(
            message=message,
            status_code=500,
            error_code="TTS_ERROR",
            details=details,
        )


class QuotaExceededError(DreamWeaverException):
    """Raised when user exceeds their quota."""

    def __init__(
        self,
        message: str = "Daily quota exceeded",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize QuotaExceededError."""
        super().__init__(
            message=message,
            status_code=429,
            error_code="QUOTA_EXCEEDED",
            details=details,
        )


class AuthenticationError(DreamWeaverException):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize AuthenticationError."""
        super().__init__(
            message=message,
            status_code=401,
            error_code="AUTHENTICATION_ERROR",
            details=details,
        )


class AuthorizationError(DreamWeaverException):
    """Raised when user is not authorized to access a resource."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize AuthorizationError."""
        super().__init__(
            message=message,
            status_code=403,
            error_code="AUTHORIZATION_ERROR",
            details=details,
        )


class NotFoundError(DreamWeaverException):
    """Raised when a resource is not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize NotFoundError."""
        super().__init__(
            message=message,
            status_code=404,
            error_code="NOT_FOUND",
            details=details,
        )


class ValidationError(DreamWeaverException):
    """Raised when validation fails."""

    def __init__(
        self,
        message: str = "Validation failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ValidationError."""
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details,
        )
