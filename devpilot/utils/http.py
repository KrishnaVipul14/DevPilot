"""Robust HTTP request helper with certifi SSL context and graceful fallback."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Any


def make_ssl_context(unverified: bool = False) -> ssl.SSLContext:
    """Create an SSLContext using certifi CA bundle if available."""
    if unverified:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def open_url(req: urllib.request.Request, timeout: float = 60) -> Any:
    """Execute urllib Request using certifi SSL certificates, retrying on certificate verify errors."""
    ctx = make_ssl_context(unverified=False)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.URLError as exc:
        # If corporate proxy or self-signed cert chain failed verification, fallback to unverified context
        err_str = str(exc).lower()
        if "certificate_verify_failed" in err_str or "self-signed" in err_str or "cert" in err_str:
            ctx_unverified = make_ssl_context(unverified=True)
            return urllib.request.urlopen(req, timeout=timeout, context=ctx_unverified)
        raise
