from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import ai_provider_manager as apm
from services.auto_parts_agent import AptState, T, format_results
from services.oem_lookup import OemResult
from services.stock_resolver import StockItem


def test_provider_stats_zero_and_serialization():
    stats = apm.ProviderStats(name="test")
    assert stats.failure_rate == 0.0
    assert stats.to_dict() == {
        "name": "test", "requests": 0, "failures": 0,
        "failure_rate": 0.0, "last_used": None, "last_failure": None,
    }


def test_record_request_success_and_failure(monkeypatch):
    monkeypatch.setattr(apm.time, "time", lambda: 123.0)
    apm._provider_stats.pop("unit-test-provider", None)
    apm.record_request("unit-test-provider", True)
    apm.record_request("unit-test-provider", False)
    stats = apm._provider_stats["unit-test-provider"]
    assert stats.requests == 2
    assert stats.failures == 1
    assert stats.last_used == 123.0
    assert stats.last_failure == 123.0
    assert stats.failure_rate == 0.5


@pytest.mark.asyncio
async def test_get_fallback_stats_includes_breaker_state(monkeypatch):
    monkeypatch.setattr(apm, "_provider_stats", {
        "openai": apm.ProviderStats("openai", requests=4, failures=1),
        "custom": apm.ProviderStats("custom", requests=1),
    })
    breaker = SimpleNamespace(state="open")
    with patch("services.circuit_breaker._breakers", {"openai": breaker}):
        rows = await apm.get_fallback_stats()
    assert rows[0]["circuit_state"] == "open"
    assert rows[1]["circuit_state"] == "closed"
    assert rows[0]["failure_rate"] == 0.25


def test_part_states_and_language_templates():
    assert AptState.IDLE == "auto_idle"
    fr = T("fr")
    ar = T("ar")
    assert "Bonjour" in fr["ask_vehicle"]
    assert "مرحبا" in ar["ask_vehicle"]
    assert T("darija")["cancelled"]


def test_format_results_with_oem_and_stock():
    oem = OemResult(
        references=[{"ref": "REF-1", "brand": "Bosch"}, {"ref": "REF-2", "brand": "Valeo"}],
        warning="Références indicatives",
    )
    items = [StockItem("Filtre à huile", "REF-1", 12.5, 3)]
    rendered = format_results(items, oem, "filtre", "Renault Clio 2018")
    assert "REF-1" in rendered
    assert "Bosch" in rendered
    assert "Références indicatives" in rendered
    assert "Filtre à huile" in rendered


def test_format_results_empty_paths():
    rendered = format_results([], None, "plaquettes", "Peugeot 206")
    assert "Aucune pièce" in rendered


@pytest.mark.asyncio
async def test_detect_part_intent_success_and_failure():
    response = MagicMock()
    response.choices = [SimpleNamespace(message=SimpleNamespace(content='```json{"is_auto_parts_request": true, "part_query": "filtre", "vehicle_hint": null, "language": "fr"}```'))]
    with patch("services.llm_gateway.chat", new=AsyncMock(return_value=response)):
        result = await __import__("services.auto_parts_agent", fromlist=["detect_part_intent"]).detect_part_intent("filtre", 7)
    assert result["part_query"] == "filtre"
    with patch("services.llm_gateway.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
        fallback = await __import__("services.auto_parts_agent", fromlist=["detect_part_intent"]).detect_part_intent("hello")
    assert fallback["is_auto_parts_request"] is False



def _auto_context(state=None, language="fr"):
    db = AsyncMock()
    wa = SimpleNamespace(send_text=AsyncMock())
    store = SimpleNamespace(
        id=10, language=language, tecdoc_api_key_enc=None,
        tecdoc_provider_id=None, autoiso_api_key_enc=None,
    )
    customer = SimpleNamespace(
        id=20, whatsapp_phone="216000000", language=language,
        conversation_state=state or {},
    )
    return db, store, customer, wa


@pytest.mark.asyncio
async def test_handle_auto_parts_idle_empty_asks_vehicle():
    from services.auto_parts_agent import handle_auto_parts_message
    db, store, customer, wa = _auto_context()
    reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": ""}, wa)
    assert "carte grise" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.COLLECT_VEHICLE
    wa.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_auto_parts_collect_vehicle_then_asks_part():
    from services.auto_parts_agent import handle_auto_parts_message
    db, store, customer, wa = _auto_context({"auto_fsm": AptState.COLLECT_VEHICLE})
    vehicle = SimpleNamespace(
        is_complete=lambda: True,
        to_dict=lambda: {"make": "Renault", "model": "Clio", "year": "2018", "engine": None, "vin": None, "source": "test"},
        summary=lambda: "Renault Clio 2018",
    )
    with patch("services.auto_parts_agent.extract_from_text", new=AsyncMock(return_value=vehicle)):
        reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "Renault Clio 2018"}, wa)
    assert "Quelle pièce" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.COLLECT_PART


@pytest.mark.asyncio
async def test_handle_auto_parts_collect_part_runs_lookup_and_returns_results():
    from services.auto_parts_agent import handle_auto_parts_message
    state = {"auto_fsm": AptState.COLLECT_PART, "auto_vehicle": {"make": "Renault", "model": "Clio", "year": "2018"}}
    db, store, customer, wa = _auto_context(state)
    oem = OemResult(references=[{"ref": "REF-X", "brand": "Bosch"}])
    item = StockItem("Filtre", "REF-X", 20.0, 4)
    response = MagicMock()
    response.choices = [SimpleNamespace(message=SimpleNamespace(content='{"part_query":"filtre huile"}'))]
    with patch("services.auto_parts_agent.detect_part_intent", new=AsyncMock(return_value={"part_query": "filtre huile"})), \
         patch("services.auto_parts_agent.lookup_oem_reference", new=AsyncMock(return_value=oem)), \
         patch("services.auto_parts_agent.resolve_stock", new=AsyncMock(return_value=[item])):
        reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "filtre huile"}, wa)
    assert "Résultats" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.SHOW_RESULTS
    assert customer.conversation_state["auto_stock_items"][0]["reference"] == "REF-X"


@pytest.mark.asyncio
async def test_handle_auto_parts_show_results_confirm_and_await_confirm():
    from services.auto_parts_agent import handle_auto_parts_message
    state = {"auto_fsm": AptState.SHOW_RESULTS, "auto_stock_items": [{"name": "Filtre", "price": 15.5, "stock": 2}]}
    db, store, customer, wa = _auto_context(state)
    reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "oui"}, wa)
    assert "Confirmation" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.AWAIT_CONFIRM
    reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "oui"}, wa)
    assert "Commande enregistrée" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.IDLE


@pytest.mark.asyncio
async def test_handle_auto_parts_cancel_and_unknown_fallback():
    from services.auto_parts_agent import handle_auto_parts_message
    db, store, customer, wa = _auto_context({"auto_fsm": AptState.COLLECT_PART})
    reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "cancel"}, wa)
    assert "Annulé" in reply
    assert customer.conversation_state["auto_fsm"] == AptState.IDLE
    customer.conversation_state = {"auto_fsm": "unexpected"}
    reply = await handle_auto_parts_message(db, store, customer, {"type": "text", "body": "x"}, wa)
    assert "carte grise" in reply
