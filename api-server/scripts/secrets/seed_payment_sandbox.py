from __future__ import annotations

from pathlib import Path

payload = """FLOUCI_BASE_URL=http://mock-flouci:8011/api
KONNECT_BASE_URL=http://mock-konnect:8012/api/v2
PAYMEE_BASE_URL=http://mock-paymee:8013/api/v2
STRIPE_MOCK_BASE_URL=http://stripe-mock:12111
MOCK_PSP=1
"""

output = Path(__file__).resolve().parents[2] / ".env.test"
existing = output.read_text(encoding="utf-8") if output.exists() else ""
if payload not in existing:
    output.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "") + payload, encoding="utf-8")
print(output)
