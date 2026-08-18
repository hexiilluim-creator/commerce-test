from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.payment_link_ai_tool import generate_payment_link_for_ai


@pytest.mark.asyncio
async def test_payment_link_requires_config():
    store = SimpleNamespace(payment_config=None, onboarding_completed=True, id=1)
    result = await generate_payment_link_for_ai(AsyncMock(), store, None, 10.0, "Commande")
    assert result == {"success": False, "url": None, "invoice_number": None, "error": "Store payment not configured"}


@pytest.mark.asyncio
async def test_payment_link_success():
    db = MagicMock()
    db.flush = AsyncMock()
    store = SimpleNamespace(payment_config={"provider": "stripe"}, onboarding_completed=True, id=3)
    customer = SimpleNamespace(id=9)
    fake_payment_link = SimpleNamespace(id=42)
    with patch("models.database.PaymentLink", return_value=fake_payment_link), \
         patch("config.settings", SimpleNamespace(SERVER_DOMAIN="https://shop.example/")), \
         patch("uuid.uuid4", side_effect=[SimpleNamespace(hex="abcdef1234567890"), SimpleNamespace(hex="token123")]):
        result = await generate_payment_link_for_ai(db, store, customer, 45.0, "Filtre", order_id=8)
    assert result["success"] is True
    assert result["payment_link_id"] == 42
    assert result["url"] == "https://shop.example/api/v1/storefront/pay/token123"
    assert result["invoice_number"].startswith("INV-3-")
    db.add.assert_called_once_with(fake_payment_link)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_link_db_error_is_reported():
    db = MagicMock()
    db.flush = AsyncMock(side_effect=RuntimeError("db down"))
    store = SimpleNamespace(payment_config={"provider": "stripe"}, onboarding_completed=True, id=3)
    with patch("models.database.PaymentLink", return_value=SimpleNamespace(id=1)):
        result = await generate_payment_link_for_ai(db, store, None, 10.0, "Commande")
    assert result["success"] is False
    assert "db down" in result["error"]
