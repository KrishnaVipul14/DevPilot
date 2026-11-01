"""Unit tests for Acme Billing & Auth."""

from __future__ import annotations

import pytest

from api import create_invoice_endpoint, quick_charge_endpoint, verify_session_endpoint
from auth import issue_token, require_user, validate_token
from billing import authorize_and_bill, create_invoice


def test_validate_and_issue_token() -> None:
    tok = issue_token("usr_42", audience="billing")
    claims = validate_token(tok, expected_audience="billing")
    assert claims == {"sub": "usr_42", "aud": "billing"}


def test_require_user_and_create_invoice_endpoint() -> None:
    tok = issue_token("usr_99", audience="billing")
    inv = create_invoice_endpoint(f"Bearer {tok}", 2500)
    assert inv["user_id"] == "usr_99"
    assert inv["amount_cents"] == 2500


def test_quick_charge_and_verify_endpoint() -> None:
    tok = issue_token("usr_77", audience="billing")
    inv = quick_charge_endpoint(tok, 1500)
    assert inv["invoice_id"] == "inv_usr_77_1500"
    session = verify_session_endpoint(tok)
    assert session["sub"] == "usr_77"


def test_authorize_and_bill_rejects_bad_token() -> None:
    with pytest.raises(PermissionError):
        authorize_and_bill("usr_1:billing:0000000000000000", 1000)


def test_create_invoice_validation() -> None:
    inv = create_invoice("usr_1", 500, "eur")
    assert inv["currency"] == "EUR"
