"""Loopback-only API authentication and secret-safe request handling."""
from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def require_local_api_token(authorization: str | None = Header(default=None)) -> None:
    """Reject all protected calls unless the configured local bearer token matches."""
    expected = os.environ.get("RINO_AGENT_API_TOKEN")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Rino Agent API token is not configured.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid local API token.")
