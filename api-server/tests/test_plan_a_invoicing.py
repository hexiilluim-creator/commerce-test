from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test-ig-token")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test-fb-token")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test-tt-token")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("DEEPSEEK_API_KEY", "ds-test-000000000000000000000000")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("SERVER_DOMAIN", "https://test.example.com")

from services.invoice_service import create_and_save_invoice


@pytest.mark.asyncio
async def test_create_and_save_invoice_from_payment_link_generates_pdf_path() -> None:
    store = SimpleNamespace(
        id=8,
        name="AutoCommerce France",
        legal_name="AutoCommerce France SAS",
        legal_address="1 rue du Commerce, Paris",
        support_email="billing@example.com",
        invoice_prefix="FAC",
        default_tax_country="FR",
        country="FR",
        tax_inclusive_pricing=True,
    )
    payment_link = SimpleNamespace(
        id=100,
        store_id=8,
        amount=120,
        currency="EUR",
        description="Commande premium",
        customer_name="Jean Martin",
        customer_email="jean@example.com",
        customer_phone="+33123456789",
        country_code="FR",
        invoice_number=None,
        invoice_url=None,
        invoice_pdf_path=None,
        subtotal_amount=None,
        tax_amount=None,
        tax_breakdown=None,
    )

    result = await create_and_save_invoice(db=None, payment_link=payment_link, store=store)

    assert result["status"] == "generated"
    assert result["invoice_number"].startswith("FAC-0008-")
    assert Path(result["pdf_path"]).exists()
    assert result["pdf_bytes"].startswith(b"%PDF")
    assert result["tax_breakdown"]
