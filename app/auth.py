"""Authentication dependencies for the HTTP API."""

from fastapi import Header, HTTPException
from .config import settings


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """Validate the configured bearer token for protected API operations.

    Args:
        authorization: Value supplied in the HTTP ``Authorization`` header.

    Returns:
        An actor label used by the API dependency system.

    Raises:
        HTTPException: If authentication is configured and the token is invalid.
    """
    if settings.api_key is None:
        return "local-development"
    if authorization != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=401, detail="authentication required")
    return "authenticated"
