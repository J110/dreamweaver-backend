"""Global exception handler middleware."""

import json
from typing import Any, Dict

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.exceptions import DreamWeaverException
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global error handler middleware that catches and formats all exceptions."""

    async def dispatch(self, request: Request, call_next: Any) -> JSONResponse:
        """
        Handle exceptions and return proper JSON responses.

        Args:
            request: HTTP request.
            call_next: Next middleware/route handler.

        Returns:
            JSON response with error details.
        """
        # Let OPTIONS (CORS preflight) requests pass through untouched
        if request.method == "OPTIONS":
            return await call_next(request)

        try:
            response = await call_next(request)
            return response
        except DreamWeaverException as e:
            logger.warning(
                f"DreamWeaver exception: {e.error_code} - {e.message}",
                extra={"extra_data": {"error_code": e.error_code, "details": e.details}},
            )
            return self._create_error_response(
                status_code=e.status_code,
                error_code=e.error_code,
                message=e.message,
                details=e.details,
            )
        except Exception as e:
            logger.error(
                f"Unhandled exception: {str(e)}",
                extra={"extra_data": {"exception_type": type(e).__name__}},
                exc_info=True,
            )
            return self._create_error_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred",
                details={"error": str(e)} if logger.level == 10 else {},
            )

    @staticmethod
    def _create_error_response(
        status_code: int,
        error_code: str,
        message: str,
        details: Dict[str, Any],
    ) -> JSONResponse:
        """
        Create JSON error response.

        Args:
            status_code: HTTP status code.
            error_code: Error code identifier.
            message: Error message.
            details: Additional error details.

        Returns:
            JSON response.
        """
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": {
                    "code": error_code,
                    "message": message,
                    "details": details,
                },
            },
        )
