"""API-key / bearer auth for the partner surface."""
from fastapi import Header

from .config import API_KEY, BEARER_TOKEN
from .envelope import ApiException

_UNAUTHORIZED = "Invalid or missing API key."


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    if x_api_key and x_api_key == API_KEY:
        return
    if authorization and authorization.startswith("Bearer "):
        if authorization.removeprefix("Bearer ").strip() == BEARER_TOKEN:
            return
    raise ApiException(401, "UNAUTHORIZED", _UNAUTHORIZED)
