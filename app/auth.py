"""Authentication dependencies for the HTTP API."""

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """Validate the configured bearer token for protected API operations.

    Args:
        credentials: Bearer credentials supplied in the HTTP ``Authorization`` header.

    Returns:
        An actor label used by the API dependency system.

    Raises:
        HTTPException: If authentication is configured and the token is invalid.
    """
    if settings.api_key is None:
        return "local-development"
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.api_key
    ):
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "authenticated"
