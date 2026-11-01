# Acme Billing & Auth Service (DevPilot Demo Repository)

This realistic sample Python service is included with DevPilot to demonstrate:
- **Code Health** detection (unused imports `F401`, undefined variable `F821`).
- **Dependency Security** auditing against **OSV.dev** (`requests==2.25.0`, `pyyaml==5.3.1`, `urllib3==1.26.4`).
- **Configuration & Setup Doctor** (`STRIPE_WEBHOOK_SECRET` and `JWT_ISSUER` used in code without being listed in `.env.example`).
- **Documentation Drift** (the Python example below calls `create_invoice()` with an outdated signature, and `validate_token()` has a stale `:param legacy_salt:` docstring).
- **Repository Intelligence Graph & Change Impact Analysis** (`validate_token()` in `auth.py` is called by `require_user()`, `create_invoice_endpoint()`, `refund_invoice_endpoint()`, and covered by `tests/test_auth_and_billing.py`).

## Setup & Installation

```bash
pip install -r requirements.txt
cp .env.example .env
pytest
```

## Quick Start Example

```python
from billing import create_invoice

# NOTE: Intentionally outdated example — `create_invoice` now requires `(user_id, amount_cents, currency="USD")`
# and no longer accepts `legacy_tax_rate` or 4 positional arguments.
invoice = create_invoice("usr_123", 4900, "USD", 0.08, legacy_tax_rate=0.05)
print(invoice)
```
