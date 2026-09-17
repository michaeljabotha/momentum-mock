"""Response envelope, request ids, and the API's error shape."""
import random
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from .config import API_VERSION

# Crockford base32 minus I, L, O, U - matches ^req_[0-9A-HJKMNP-TV-Z]{26}$
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_request_id() -> str:
    return "req_" + "".join(random.choices(_ULID_ALPHABET, k=26))


def meta(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "version": API_VERSION,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def success(data: list[Any], pagination: dict[str, int], request_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "message": None,
        "error": None,
        "pagination": pagination,
        "meta": meta(request_id),
    }


def failure(code: str, message: str, request_id: str,
            details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {
        "success": False,
        "data": None,
        "message": message,
        "error": error,
        "pagination": None,
        "meta": meta(request_id),
    }


class ApiException(HTTPException):
    """Raised anywhere in the request path; rendered into the error envelope."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: list[dict[str, str]] | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details


def validation_error(message: str, field: str, field_code: str) -> ApiException:
    return ApiException(400, "VALIDATION_ERROR", message,
                        [{"field": field, "code": field_code, "message": message}])
