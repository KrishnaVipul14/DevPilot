"""HTTP API route handlers for Acme Billing."""

from __future__ import annotations

from typing import Any, Callable

from auth import require_user, validate_token
from billing import authorize_and_bill, create_invoice


class SimpleRouter:
    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn
        return _wrap

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn
        return _wrap


app = SimpleRouter()


@app.post("/api/v1/invoices")
def create_invoice_endpoint(auth_header: str, amount_cents: int) -> dict[str, Any]:
    user_id = require_user(auth_header)
    return create_invoice(user_id=user_id, amount_cents=amount_cents)


@app.post("/api/v1/invoices/quick-charge")
def quick_charge_endpoint(token: str, amount_cents: int) -> dict[str, Any]:
    return authorize_and_bill(token=token, amount_cents=amount_cents)


@app.get("/api/v1/auth/verify")
def verify_session_endpoint(token: str) -> dict[str, Any]:
    return validate_token(token)
