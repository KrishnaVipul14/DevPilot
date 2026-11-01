"""Invoice creation, webhook verification, and discount calculation."""

from __future__ import annotations

import os
import sys  # Intentionally unused import (F401)
from typing import Any

from auth import validate_token


def create_invoice(user_id: str, amount_cents: int, currency: str = "USD") -> dict[str, Any]:
    """Create a billing invoice record for `user_id`."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    return {
        "invoice_id": f"inv_{user_id}_{amount_cents}",
        "user_id": user_id,
        "amount_cents": amount_cents,
        "currency": currency.upper(),
        "status": "open",
    }


def authorize_and_bill(token: str, amount_cents: int) -> dict[str, Any]:
    """Validate caller token and create an invoice."""
    claims = validate_token(token, expected_audience="billing")
    return create_invoice(str(claims["sub"]), amount_cents=amount_cents)


def verify_webhook_signature(payload: bytes) -> bool:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    return bool(secret and payload)


def compute_legacy_discount(subtotal_cents: int) -> int:
    """Intentionally references an undefined identifier `default_discount_rate` (F821)."""
    return int(subtotal_cents * default_discount_rate)
