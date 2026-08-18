from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from api.v1.ai import SemanticSearchRequest, VisionUrlRequest, semantic_search, test_vision_url as vision_url_handler


def test_ai_request_schemas_enforce_security_limits():
    assert SemanticSearchRequest(query="brake", top_k=5).top_k == 5
    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="x" * 501)
    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="x", top_k=0)
    assert VisionUrlRequest(image_url="https://cdn.example/a.jpg", search_stock=False).search_stock is False


@pytest.mark.asyncio
async def test_semantic_search_scopes_store_and_returns_count():
    db = AsyncMock()
    with patch("api.v1.ai._sid", return_value=12), patch("api.v1.ai.search_products", new=AsyncMock(return_value=[{"id": 1}, {"id": 2}])) as search:
        result = await semantic_search(SemanticSearchRequest(query="plaquettes frein", top_k=2), db)
    assert result["count"] == 2
    search.assert_awaited_once()
    assert search.await_args.args[1] == 12


@pytest.mark.asyncio
async def test_vision_url_can_skip_stock_search():
    db = AsyncMock()
    with patch("api.v1.ai._sid", return_value=3), patch("api.v1.ai.analyze_image_url", new=AsyncMock(return_value={"brand": "Bosch"})), patch("api.v1.ai.find_best_match", new=AsyncMock()) as match:
        result = await vision_url_handler(VisionUrlRequest(image_url="https://cdn.example/a.jpg", search_stock=False), db)
    assert result == {"vision_analysis": {"brand": "Bosch"}}
    match.assert_not_awaited()
