from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel

DataT = TypeVar("DataT")

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int

class APIResponse(BaseModel, Generic[DataT]):
    success: bool = True
    data: Optional[DataT] = None
    error: Optional[str] = None
    meta: Optional[PaginationMeta] = None

def success_response(data: Any = None, meta: Optional[PaginationMeta] = None) -> APIResponse[Any]:
    """Returns a standardized success response envelope."""
    return APIResponse(success=True, data=data, error=None, meta=meta)

def error_response(error_message: str, data: Any = None) -> APIResponse[Any]:
    """Returns a standardized error response envelope."""
    return APIResponse(success=False, data=data, error=error_message, meta=None)
