"""
Standard API Response Wrappers
Generic response schemas for API endpoints.
"""

from typing import TypeVar, Generic, List, Optional, Dict, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""
    
    success: bool = Field(description="Whether the operation was successful")
    data: Optional[T] = Field(default=None, description="Response data")
    message: str = Field(default="", description="Response message")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="List of errors")
    
    @classmethod
    def success_response(cls, data: T, message: str = "Success") -> "ApiResponse[T]":
        """Create a successful response."""
        return cls(success=True, data=data, message=message)
    
    @classmethod
    def error_response(cls, message: str, errors: Optional[List[Dict[str, Any]]] = None) -> "ApiResponse[T]":
        """Create an error response."""
        return cls(success=False, message=message, errors=errors or [])


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    
    items: List[T] = Field(description="Items in current page")
    total: int = Field(ge=0, description="Total items")
    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, description="Items per page")
    has_more: bool = Field(description="Whether more pages exist")
    
    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        return (self.total + self.page_size - 1) // self.page_size


class ErrorResponse(BaseModel):
    """Error response."""
    
    error_code: str = Field(description="Error code")
    message: str = Field(description="Error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error details")
    
    def __init__(self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None, **kwargs):
        """Initialize error response."""
        super().__init__(error_code=error_code, message=message, details=details, **kwargs)
