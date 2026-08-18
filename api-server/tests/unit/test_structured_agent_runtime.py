from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services import structured_agent


def test_menu_lock_key_and_product_formatting():
    assert "Bienvenue" in structured_agent.send_main_menu("fr")
    assert "Chnouwa" in structured_agent.send_main_menu("darija")
    assert structured_agent._customer_lock_key(42) == "structured_agent:customer:42"
    product = SimpleNamespace(name="Filtre", price=25.5, currency="TND", description="Premium", stock_qty=3)
    assert "Filtre" in structured_agent.format_product(product)
    assert "Filtre" in structured_agent.format_product_localized(product, "fr")


@pytest.mark.asyncio
async def test_detect_intent_validates_emotion_and_falls_back():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"product_search","emotion":"invalid","product_query":"filter","preferences":[]}'))])
    with patch("services.llm_gateway.chat", new=AsyncMock(return_value=response)), patch("services.structured_agent.parse_llm_json", return_value={"intent": "product_search", "emotion": "invalid", "product_query": "filter", "preferences": []}):
        result = await structured_agent.detect_intent_and_emotion("Je cherche un filtre")
    assert result["intent"] == "product_search"
    assert result["emotion"] == "interested"

    with patch("services.llm_gateway.chat", new=AsyncMock(side_effect=RuntimeError("offline"))):
        fallback = await structured_agent.detect_intent_and_emotion("hello")
    assert fallback["intent"] == "other" and fallback["emotion"] == "interested"


@pytest.mark.asyncio
async def test_processing_lock_releases_acquired_lock():
    lock = AsyncMock()
    lock.try_acquire.return_value = True
    with patch("services.redis_lock.lock_service", lock):
        async with structured_agent._customer_processing_lock(7):
            pass
    lock.try_acquire.assert_awaited_once()
    lock.release.assert_awaited_once_with("structured_agent:customer:7")
