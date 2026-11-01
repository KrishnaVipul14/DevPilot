# Acme Billing & Auth Service (DevPilot Demo App)

This is a small sample Python project included with DevPilot so you can test every feature right away on realistic code.

It intentionally contains a handful of common problems across its files:

1. **Unused imports (`F401`)** — `import json` in `auth.py` and `import sys` in `billing.py`.
2. **Undefined variable (`F821`)** — `compute_legacy_discount()` in `billing.py` multiplies by `default_discount_rate`, which is never defined.
3. **Vulnerable dependencies** — `requirements.txt` pins old versions (`pyyaml==5.3.1`, `urllib3==1.26.4`, `requests==2.25.0`) that have real security advisories in **OSV.dev**.
4. **Missing `.env.example` variables** — `auth.py` reads `JWT_ISSUER` and `billing.py` reads `STRIPE_WEBHOOK_SECRET`, but neither is listed in `.env.example`.
5. **Outdated documentation** — `validate_token()` has a stale `:param legacy_salt:` in its docstring, and the code example below calls `create_invoice()` with old arguments that don't match the current function in `billing.py`.
6. **Connected call graph & tests** — `validate_token()` in `auth.py` is called by `require_user()` and `authorize_and_bill()`, used by 3 HTTP routes in `api.py`, and tested in `tests/test_auth_and_billing.py`.

## Setup & Installation

```bash
pip install -r requirements.txt
cp .env.example .env
pytest
```

## Quick Start Example

```python
from billing import create_invoice

# Intentionally outdated example so DevPilot's documentation-drift analyzer catches it:
# `create_invoice` only takes (user_id, amount_cents, currency="USD").
invoice = create_invoice("usr_123", 4900, "USD", 0.08, legacy_tax_rate=0.05)
print(invoice)
```
