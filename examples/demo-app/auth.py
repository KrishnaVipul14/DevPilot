"""Authentication and token validation helpers for Acme Billing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any


def _signing_secret() -> str:
    return os.environ.get("JWT_SIGNING_SECRET", "dev-only-placeholder")


def get_jwt_issuer() -> str:
    # Reads JWT_ISSUER without default; intentionally missing from .env.example
    return os.environ["JWT_ISSUER"]


def validate_token(token: str, expected_audience: str = "billing") -> dict[str, Any]:
    """Validate a signed bearer token and return its claims dictionary.

    :param token: Compact token string `<user_id>:<audience>:<signature>`.
    :param expected_audience: Expected audience claim.
    :param legacy_salt: Outdated parameter kept in docstring (triggers documentation drift).
    """
    if not token or ":" not in token:
        raise ValueError("Malformed token")
    parts = token.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid token structure")
    user_id, audience, sig = parts
    if audience != expected_audience:
        raise PermissionError(f"Invalid token audience: {audience}")
    expected_sig = hmac.new(
        _signing_secret().encode("utf-8"),
        f"{user_id}:{audience}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected_sig):
        raise PermissionError("Token signature mismatch")
    return {"sub": user_id, "aud": audience}


def issue_token(user_id: str, audience: str = "billing") -> str:
    sig = hmac.new(
        _signing_secret().encode("utf-8"),
        f"{user_id}:{audience}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{user_id}:{audience}:{sig}"


def require_user(auth_header: str) -> str:
    """Extract and validate a Bearer token, returning the authenticated `user_id`."""
    if not auth_header.startswith("Bearer "):
        raise PermissionError("Missing Bearer prefix")
    raw_token = auth_header[len("Bearer ") :].strip()
    claims = validate_token(raw_token, expected_audience="billing")
    return str(claims["sub"])
