from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.oem_lookup import OemResult, _lookup_autoiso, _lookup_tecdoc, lookup_oem_reference


def test_oem_result_helpers():
    result = OemResult(references=[{"ref": "A"}, {"ref": "B"}, {}, {"ref": "C"}], source="test")
    assert result.has_results() is True
    assert result.best_refs() == ["A", "B", "C"]
    assert OemResult().has_results() is False


@pytest.mark.asyncio
async def test_oem_lookup_falls_back_to_llm_when_sources_empty():
    llm_result = OemResult(references=[{"ref": "LLM-1"}], source="llm")
    with patch("services.oem_lookup._lookup_tecdoc", new=AsyncMock(return_value=OemResult(source="tecdoc"))), \
         patch("services.oem_lookup._lookup_autoiso", new=AsyncMock(return_value=OemResult(source="autoiso"))), \
         patch("services.oem_lookup._lookup_llm", new=AsyncMock(return_value=llm_result)):
        result = await lookup_oem_reference("Peugeot", "206", "2008", "filtre", tecdoc_api_key="k", tecdoc_provider_id="1", autoiso_api_key="a")
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_autoiso_and_tecdoc_response_mapping():
    response = SimpleNamespace(json=lambda: {"parts": [{"oem_number": "X", "brand": "Bosch", "name": "Filtre"}]}, raise_for_status=lambda: None)
    client = AsyncMock()
    client.__aenter__.return_value.get.return_value = response
    with patch("services.oem_lookup.httpx.AsyncClient", return_value=client):
        result = await _lookup_autoiso("P", "M", "2020", "filter", "key")
    assert result.source == "autoiso" and result.best_refs() == ["X"]

    vehicle = SimpleNamespace(json=lambda: {"array": [{"carId": 7}]}, raise_for_status=lambda: None)
    articles = SimpleNamespace(json=lambda: {"articles": [{"articleNumber": "Y", "brandName": "Valeo", "genericArticle": {"genericArticleDescription": "Brake"}}]}, raise_for_status=lambda: None)
    client = AsyncMock()
    client.__aenter__.return_value.post.side_effect = [vehicle, articles]
    with patch("services.oem_lookup.httpx.AsyncClient", return_value=client):
        result = await _lookup_tecdoc("P", "M", "2020", "brake", "key", "1")
    assert result.source == "tecdoc" and result.best_refs() == ["Y"]
