from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import structured_agent as sa


def store(**overrides):
    values = dict(id=2, name="Store", conversation_timeout_min=30, payment_config=None, onboarding_completed=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def customer(**overrides):
    values = dict(
        id=9,
        name="Ali",
        whatsapp_phone="21600000000",
        preferences={},
        last_emotion=None,
        conversation_state={},
        last_message_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def product(**overrides):
    values = dict(id=4, name="Filtre", price=12.5, stock_qty=7, description="Produit fiable")
    values.update(overrides)
    return SimpleNamespace(**values)


def test_send_main_menu_supports_french_and_darija():
    assert "Bienvenue" in sa.send_main_menu("fr")
    assert "Asslema" in sa.send_main_menu("darija")


def test_customer_lock_acquires_releases_and_falls_back_when_busy():
    lock = AsyncMock()
    lock.try_acquire.side_effect = [True]
    lock.release = AsyncMock()
    with patch("services.redis_lock.lock_service", lock):
        async def run():
            async with sa._customer_processing_lock(9):
                pass
        import asyncio
        asyncio.run(run())
    lock.try_acquire.assert_awaited_once()
    lock.release.assert_awaited_once_with("structured_agent:customer:9")


def test_customer_lock_key_is_stable():
    assert sa._customer_lock_key(12) == "structured_agent:customer:12"


@pytest.mark.asyncio
async def test_detect_intent_and_emotion_normalizes_unknown_emotion_and_falls_back():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"greeting","emotion":"unknown","preferences":[]}'))])
    with patch("services.llm_gateway.chat", new=AsyncMock(return_value=response)), patch(
        "services.structured_agent.parse_llm_json", return_value={"intent": "greeting", "emotion": "unknown", "preferences": []}
    ):
        result = await sa.detect_intent_and_emotion("bonjour")
    assert result["emotion"] == "interested"
    with patch("services.llm_gateway.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await sa.detect_intent_and_emotion("x")
    assert result["intent"] == "other"
    assert result["emotion"] == "interested"


@pytest.mark.asyncio
async def test_load_customer_for_update_uses_locked_row_or_fallback():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    c = customer()
    assert await sa._load_customer_for_update(db, c) is c
    db.execute.assert_awaited_once()


def test_format_product_localized_truncates_description_and_localizes():
    p = product(description="x" * 120)
    french = sa.format_product(p)
    darija = sa.format_product_localized(p, "darija")
    assert "Prix" in french and "..." in french
    assert "Soum" in darija and "techri" in darija


@pytest.mark.asyncio
async def test_handle_main_menu_routes_product_order_support_and_unknown():
    c = customer()
    s = store()
    state = sa.ConversationState(c, {"last_lang": "fr"})
    assert "recherchez" in (await sa.handle_main_menu(MagicMock(), s, c, {"intent": "other"}, "1", state=state))
    assert state["fsm_state"] == sa.BROWSING
    state["last_lang"] = "fr"
    assert "suivre" in (await sa.handle_main_menu(MagicMock(), s, c, {"intent": "order_status"}, "x", state=state)).lower()
    assert "conseiller" in (await sa.handle_main_menu(MagicMock(), s, c, {"intent": "talk_to_human"}, "x", state=state)).lower()
    assert "1" in (await sa.handle_main_menu(MagicMock(), s, c, {"intent": "other"}, "x", state=state))


@pytest.mark.asyncio
async def test_handle_browsing_handles_menu_switch_no_results_and_product_format():
    c = customer(conversation_state={"fsm_state": sa.BROWSING}, preferences={"sport": 3})
    s = store()
    state = sa.ConversationState.from_customer(c)
    assert "Bienvenue" in (await sa.handle_browsing(MagicMock(), s, c, {"intent": "other"}, "0", state=state))
    state["fsm_state"] = sa.BROWSING
    with patch("services.structured_agent.search_products", new=AsyncMock(return_value=[])):
        assert "pas trouvé" in (await sa.handle_browsing(MagicMock(), s, c, {"intent": "other"}, "plaquette", state=state))
    state["fsm_state"] = sa.BROWSING
    with patch("services.structured_agent.search_products", new=AsyncMock(return_value=[product()])):
        response = await sa.handle_browsing(MagicMock(), s, c, {"intent": "product_search", "product_query": "filtre"}, "filtre", state=state)
    assert "Filtre" in response
    assert state["selected_product_id"] == 4


@pytest.mark.asyncio
async def test_search_products_uses_advanced_results_then_sql_fallback():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [product()]
    db.execute.return_value = result
    with patch("services.structured_agent.existing_search_products", new=AsyncMock(return_value=[{"product_id": 4}])):
        result = await sa.search_products(db, 2, "filtre")
    assert len(result) == 1
    with patch("services.structured_agent.existing_search_products", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await sa.search_products(db, 2, "filtre")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_handle_order_confirmation_returns_menu_without_product_and_summary_with_product():
    c = customer(conversation_state={})
    s = store()
    state = sa.ConversationState.from_customer(c)
    reply = await sa.handle_order_confirmation(MagicMock(), s, c, {}, "INIT", state=state)
    assert "menu" in reply.lower()
    c.conversation_state = {"selected_product_id": 4, "last_lang": "fr", "fsm_state": sa.ORDER_CONFIRMATION}
    state = sa.ConversationState.from_customer(c)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = product()
    db.execute.return_value = result
    reply = await sa.handle_order_confirmation(db, s, c, {}, "INIT", state=state)
    assert "Résumé" in reply


@pytest.mark.asyncio
async def test_route_returns_safe_message_on_handler_error():
    db = MagicMock()
    c = customer(conversation_state={"fsm_state": sa.MAIN_MENU})
    with patch("services.structured_agent.handle_main_menu", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await sa.route(db, store(), c, {"intent": "other"}, "x", MagicMock())
    assert "petite erreur" in result


@pytest.mark.asyncio
async def test_create_order_safe_checks_stock_and_builds_pending_order():
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = product(); db.execute.return_value = result
    db.add = MagicMock()
    order = await sa.create_order_safe(db, store(), customer(), 4)
    assert order is not None and order.status == sa.OrderStatus.PENDING
    assert product().stock_qty == 7
    assert db.add.call_count == 2
    empty = MagicMock(); empty.scalar_one_or_none.return_value = None; db.execute.return_value = empty
    assert await sa.create_order_safe(db, store(), customer(), 99) is None


@pytest.mark.asyncio
async def test_order_confirmation_handles_missing_product_cancel_invalid_and_stock_race():
    c = customer(conversation_state={"selected_product_id": 4, "last_lang": "fr", "fsm_state": sa.ORDER_CONFIRMATION}); s = store(); db = AsyncMock()
    result = MagicMock(); result.scalar_one_or_none.return_value = product(); db.execute.return_value = result
    state = sa.ConversationState.from_customer(c)
    assert "confirm" in (await sa.handle_order_confirmation(db, s, c, {}, "maybe", state=state)).lower()
    state = sa.ConversationState.from_customer(c)
    assert "souci" in (await sa.handle_order_confirmation(db, s, c, {}, "Non", state=state)).lower()
    with patch.object(sa, "create_order_safe", new=AsyncMock(return_value=None)):
        state = sa.ConversationState.from_customer(c)
        assert "rupture" in (await sa.handle_order_confirmation(db, s, c, {}, "Oui", state=state)).lower()
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute.return_value = missing
    c_missing = customer(conversation_state={"selected_product_id": 4, "last_lang": "fr", "fsm_state": sa.ORDER_CONFIRMATION})
    state = sa.ConversationState.from_customer(c_missing)
    assert "disponible" in (await sa.handle_order_confirmation(db, s, c_missing, {}, "INIT", state=state)).lower()


@pytest.mark.asyncio
async def test_order_confirmation_success_adds_payment_link_when_configured():
    c = customer(conversation_state={"selected_product_id": 4, "last_lang": "fr", "fsm_state": sa.ORDER_CONFIRMATION}); s = store(payment_config={"provider": "x"}, onboarding_completed=True); db = AsyncMock()
    result = MagicMock(); result.scalar_one_or_none.return_value = product(); db.execute.return_value = result
    fake_order = SimpleNamespace(id=22, total_amount=12.5, items=[{"name": "Filtre"}])
    with patch.object(sa, "create_order_safe", new=AsyncMock(return_value=fake_order)), patch("services.payment_link_ai_tool.generate_payment_link_for_ai", new=AsyncMock(return_value={"success": True, "url": "https://pay.test/22", "invoice_number": "INV-22"})):
        reply = await sa.handle_order_confirmation(db, s, c, {}, "Oui", state=sa.ConversationState.from_customer(c))
    assert "Commande #22" in reply and "https://pay.test/22" in reply


@pytest.mark.asyncio
async def test_relance_users_filters_and_sends_emotion_specific_message():
    from datetime import UTC, datetime, timedelta
    class Result:
        def __init__(self, rows=None, scalar=None): self.rows = rows or []; self.scalar = scalar
        def fetchall(self): return [(2,)]
        def scalars(self): return self
        def all(self): return self.rows
        def scalar_one_or_none(self): return self.scalar
    eligible = customer(conversation_state={"fsm_state": sa.BROWSING}, last_emotion="hesitant", last_message_at=datetime.now(UTC) - timedelta(minutes=45), store_id=2)
    idle = customer(conversation_state={"fsm_state": sa.IDLE}, last_message_at=datetime.now(UTC) - timedelta(minutes=45), store_id=2)
    recent = customer(conversation_state={"fsm_state": sa.BROWSING, "relanced_at": datetime.now(UTC).isoformat()}, last_message_at=datetime.now(UTC) - timedelta(minutes=45), store_id=2)
    db = AsyncMock(); db.execute.side_effect = [Result(), Result([eligible, idle, recent]), Result(scalar=store(id=2))]; db.add = MagicMock()
    class Session:
        async def __aenter__(self): return db
        async def __aexit__(self, *args): return False
    captured = {}
    def run_async(coro): captured["coro"] = coro
    sent = []
    class WA:
        def __init__(self, store): pass
        async def send_text(self, phone, message): sent.append((phone, message))
    with patch("models.database.AsyncSessionLocal", return_value=Session()), patch("services.tasks.run_async", side_effect=run_async), patch("services.tenant_access.is_tenant_active", new=AsyncMock(return_value=True)), patch("utils.whatsapp_client.WhatsAppClient", WA):
        sa.relance_users()
        await captured["coro"]
    assert len(sent) == 1 and "coup de pouce" in sent[0][1]
    assert eligible.conversation_state["relanced_at"]
    db.commit.assert_awaited_once()
