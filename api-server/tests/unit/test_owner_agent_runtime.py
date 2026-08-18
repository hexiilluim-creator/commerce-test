from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.database import OrderStatus
from services.owner_agent import _detect_owner_intent, _handle_orders_summary, _handle_stock_check


@pytest.mark.asyncio
async def test_detect_owner_intent_success_and_failure():
    response = MagicMock()
    response.choices = [SimpleNamespace(message=SimpleNamespace(content='```json{"intent":"stock_check","product_hint":"filtre"}```'))]
    with patch("services.owner_agent.llm_chat", new=AsyncMock(return_value=response)):
        result = await _detect_owner_intent("stock filtre", tenant_id=3)
    assert result["intent"] == "stock_check"
    with patch("services.owner_agent.llm_chat", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert (await _detect_owner_intent("hello"))["intent"] == "unknown"


@pytest.mark.asyncio
async def test_handle_stock_check_empty_and_low_stock():
    db = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    db.execute.return_value = empty
    store = SimpleNamespace(id=4)
    assert "Aucun produit" in await _handle_stock_check(db, store, "filtre")

    products = [
        SimpleNamespace(name="Filtre", stock_qty=0, price=12.5),
        SimpleNamespace(name="Huile", stock_qty=7, price=20),
    ]
    nonempty = MagicMock()
    nonempty.scalars.return_value.all.return_value = products
    db.execute.return_value = nonempty
    text = await _handle_stock_check(db, store, None)
    assert "Filtre" in text and "Stock bas" in text and "12.500" in text


@pytest.mark.asyncio
async def test_handle_orders_summary_empty_and_totals():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    store = SimpleNamespace(id=4)
    assert "Aucune commande" in await _handle_orders_summary(db, store, "today")

    orders = [
        SimpleNamespace(status=OrderStatus.PAID, total_amount=100.0, items=[{"product_name": "Filtre"}]),
        SimpleNamespace(status=OrderStatus.PENDING, total_amount=20.0, items=[]),
        SimpleNamespace(status=OrderStatus.CANCELLED, total_amount=5.0, items=[]),
    ]
    result.scalars.return_value.all.return_value = orders
    text = await _handle_orders_summary(db, store, "week")
    assert "3" in text and "100.000 DT" in text and "Filtre" in text


from services.owner_agent import _handle_clients_stats, _handle_set_stock_alert, _handle_broadcast, handle_owner_message


@pytest.mark.asyncio
async def test_clients_stats_and_set_stock_alert():
    db = AsyncMock()
    r1 = MagicMock(); r1.scalar.return_value = 10
    r2 = MagicMock(); r2.scalar.return_value = 4
    r3 = MagicMock(); r3.scalar.return_value = 2
    db.execute = AsyncMock(side_effect=[r1, r2, r3]); store = SimpleNamespace(id=4, payment_config={})
    text = await _handle_clients_stats(db, store)
    assert "10" in text and "20.0%" in text
    db.commit = AsyncMock()
    alert = await _handle_set_stock_alert(db, store, 3)
    assert store.payment_config["stock_alert_threshold"] == 3 and "3 unités" in alert


@pytest.mark.asyncio
async def test_broadcast_confirmation_and_send_success_failure():
    db = AsyncMock(); count = MagicMock(); count.scalar.return_value = 2
    db.execute = AsyncMock(return_value=count); store = SimpleNamespace(id=4)
    state = {}
    pending = await _handle_broadcast(db, store, MagicMock(), "Promo", False, "owner", state)
    assert "confirmation" in pending and state["pending_broadcast"] == "Promo"
    rows = MagicMock(); rows.fetchall.return_value = [("2161",), ("2162",)]
    db.execute.return_value = rows
    wa = MagicMock(); wa.send_text = AsyncMock(side_effect=[None, RuntimeError("down")])
    with patch("asyncio.sleep", new=AsyncMock()):
        result = await _handle_broadcast(db, store, wa, "", True, "owner", state)
    assert "Envoyé : *1*" in result and "Échecs : *1*" in result


@pytest.mark.asyncio
async def test_handle_owner_message_help_unknown_and_cancel_pending():
    db = AsyncMock(); db.commit = AsyncMock(); wa = AsyncMock()
    store = SimpleNamespace(id=4, payment_config={"owner_session": {"pending_broadcast": "x"}})
    with patch("services.owner_agent._handle_broadcast", new=AsyncMock(return_value="done")):
        assert await handle_owner_message(db, store, "oui", wa, "owner") == "done"
    store.payment_config = {}
    with patch("services.owner_agent._detect_owner_intent", new=AsyncMock(return_value={"intent": "help"})):
        assert "Commandes disponibles" in await handle_owner_message(db, store, "aide", wa, "owner")
    with patch("services.owner_agent._detect_owner_intent", new=AsyncMock(return_value={"intent": "unknown"})):
        assert "non reconnue" in await handle_owner_message(db, store, "xyz", wa, "owner")
