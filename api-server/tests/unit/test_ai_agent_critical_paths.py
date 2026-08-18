from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import ai_agent as agent


def customer(**overrides):
    values = dict(
        id=7,
        language="fr",
        conversation_state={},
        last_emotion=None,
        last_message_at=None,
        whatsapp_phone="21600000000",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def store(**overrides):
    values = dict(id=3, name="Auto Store", language="fr", ai_agent_prompt="", conversation_timeout_min=30)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_json_depth_and_state_sanitization_reject_invalid_large_and_deep_states():
    assert agent._sanitize_conversation_state(None) == {}
    assert agent._sanitize_conversation_state(["bad"]) == {}
    assert agent._sanitize_conversation_state({"a": object()}) == {}
    assert agent._sanitize_conversation_state({"data": "x" * (agent._STATE_MAX_BYTES + 1)}) == {}
    deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
    assert agent._sanitize_conversation_state(deep) == {}
    valid = {"fsm_state": agent.State.BROWSING, "preferences": {"color": "blue"}}
    assert agent._sanitize_conversation_state(valid) == valid


def test_build_system_prompt_includes_language_state_memory_preferences_and_emotion():
    c = customer(
        language="fr",
        last_emotion="frustrated",
        conversation_state={
            "fsm_state": agent.State.PRODUCT_SHOWN,
            "last_messages": ["one", "two", "three", "four"],
            "preferences": {"brand": "OEM", "color": "black"},
        },
    )
    prompt = agent.build_system_prompt(store(), c)
    assert "Auto Store" in prompt
    assert "État FSM: product_shown" in prompt
    assert "  - three" in prompt and "  - four" in prompt and "  - one" not in prompt
    assert "brand:OEM" in prompt
    assert "Client frustré" in prompt


def test_cache_key_is_deterministic_and_limited():
    assert agent._cache_key_fn("abc") == agent._cache_key_fn("abc")
    assert agent._cache_key_fn("a" * 100) == agent._cache_key_fn("a" * 101)
    assert agent._cache_key_fn("a" * 99) != agent._cache_key_fn("a" * 100)


@pytest.mark.asyncio
async def test_detect_intent_and_reply_parses_json_and_falls_back_on_bad_model_output():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='```json{"intent":"greeting","reply":"Bonjour"}```'))])
    with patch("services.ai_agent.llm_chat", new=AsyncMock(return_value=response)):
        intent, reply = await agent.detect_intent_and_reply("bonjour", store(), customer(), tenant_id=3)
    assert intent["intent"] == "greeting"
    assert reply == "Bonjour"
    with patch("services.ai_agent.llm_chat", new=AsyncMock(side_effect=RuntimeError("down"))):
        intent, reply = await agent.detect_intent_and_reply("bonjour", store(), customer())
    assert intent["intent"] == "other"
    assert reply is None


@pytest.mark.asyncio
async def test_detect_intent_and_delivery_extraction_fallbacks_are_fail_safe():
    with patch("services.ai_agent.llm_chat", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert (await agent.detect_intent("x"))["intent"] == "other"
        delivery = await agent._extract_delivery_info("x")
    assert delivery == {"complete": False, "missing": ["nom", "adresse"]}


@pytest.mark.asyncio
async def test_generate_reply_returns_trimmed_content():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  réponse  "))])
    with patch("services.ai_agent.llm_chat", new=AsyncMock(return_value=response)):
        assert await agent.generate_reply("system", "context") == "réponse"


def test_check_timeout_handles_missing_naive_and_recent_timestamps():
    assert agent._check_timeout(customer(last_message_at=None), 30) is False
    old = datetime.now(UTC) - timedelta(minutes=31)
    assert agent._check_timeout(customer(last_message_at=old), 30) is True
    naive_recent = datetime.utcnow() - timedelta(minutes=1)
    assert agent._check_timeout(customer(last_message_at=naive_recent), 30) is False


@pytest.mark.asyncio
async def test_create_order_rejects_missing_product_or_invalid_delivery_before_db_mutation():
    db = AsyncMock()
    s = store()
    c = customer(conversation_state={})
    assert await agent._create_order_from_state(db, s, c, {"name": "Ali", "address": "Tunis"}) is None
    c.conversation_state = {"last_product": {"product_id": 1, "price": 10, "name": "Part"}, "quantity": 0}
    assert await agent._create_order_from_state(db, s, c, {"name": "A", "address": "x"}) is None
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_button_confirm_cancel_and_unknown_update_customer_and_send_reply():
    db = AsyncMock()
    db.add = MagicMock()
    wa = AsyncMock()
    s = store()
    c = customer(conversation_state={"fsm_state": agent.State.PRODUCT_SHOWN, "last_product": {"name": "Brake"}})
    with patch("services.ai_agent.generate_reply", new=AsyncMock(return_value="reply")), patch(
        "services.ai_agent._log_transition", new=AsyncMock()
    ):
        assert await agent.handle_button_reply(db, s, c, "confirm_order", "Commander", wa) == "reply"
        assert c.conversation_state["fsm_state"] == agent.State.AWAITING_DELIVERY
        assert await agent.handle_button_reply(db, s, c, "cancel", "Annuler", wa) == "reply"
        assert c.conversation_state == {"fsm_state": agent.State.IDLE}
        assert await agent.handle_button_reply(db, s, c, "other", "Autre", wa) == "reply"
    assert wa.send_text.await_count == 3
    assert db.commit.await_count == 3


@pytest.mark.asyncio
async def test_lookup_product_by_query_maps_active_stock_results():
    products = [SimpleNamespace(id=1, name="Brake Pad", price=42, stock_qty=3, image_url="/p.jpg")]
    result = MagicMock(); result.scalars.return_value.all.return_value = products
    db = AsyncMock(); db.execute.return_value = result
    found = await agent.lookup_product_by_query(db, 3, "brake")
    assert found == [{"product_id": 1, "name": "Brake Pad", "price": 42, "stock": 3, "image_url": "/p.jpg"}]


@pytest.mark.asyncio
async def test_reply_cache_reads_and_writes_with_fail_open_redis_client():
    redis = AsyncMock(); redis.get.return_value = "cached reply"
    with patch("services.redis_lock.get_redis", return_value=redis):
        assert await agent._get_reply_cache(3, "abc") == "cached reply"
        await agent._set_reply_cache(3, "abc", "new reply")
    redis.get.assert_awaited_once_with("reply_cache:3:abc")
    redis.setex.assert_awaited_once_with("reply_cache:3:abc", agent._CACHE_TTL, "new reply")
    broken = MagicMock(); broken.get = AsyncMock(side_effect=RuntimeError("redis down")); broken.setex = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch("services.redis_lock.get_redis", return_value=broken):
        assert await agent._get_reply_cache(3, "bad") is None
        assert await agent._set_reply_cache(3, "bad", "x") is None


@pytest.mark.asyncio
async def test_create_order_reserves_stock_and_maps_clic_provider():
    db = AsyncMock()
    db.add = MagicMock()
    product = SimpleNamespace(id=1, store_id=3, stock_qty=5, stock_reserved=1)
    result = MagicMock(); result.scalar_one_or_none.return_value = product; db.execute.return_value = result
    c = customer(conversation_state={"last_product": {"product_id": 1, "price": 10, "name": "Part"}, "quantity": 2})
    order = await agent._create_order_from_state(db, store(), c, {"name": "Ali", "address": "Tunis Centre", "payment_method": "clic"})
    assert order is not None and order.payment_provider == "clix" and product.stock_reserved == 3
    assert db.flush.await_count == 1


@pytest.mark.asyncio
async def test_handle_image_message_product_match_sends_card_without_text_reply():
    db = AsyncMock(); db.add = MagicMock()
    locked = MagicMock(); locked.scalar_one_or_none.return_value = customer(); db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    vision = {"type": "part", "confidence": 0.9, "description_fr": "frein"}
    match = {"found": True, "match_score": 0.9, "name": "Brake", "price": 25, "stock": 4, "product_id": 1}
    with patch.object(agent, "analyze_whatsapp_image", new=AsyncMock(return_value=vision)), patch.object(agent, "find_best_match", new=AsyncMock(return_value=match)), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Voici le produit")), patch.object(agent, "_log_transition", new=AsyncMock()):
        response = await agent.handle_image_message(db, store(), customer(), "media-1", wa)
    assert response["match"] == match and response["reply"] == "Voici le produit"
    wa.send_product_card.assert_awaited_once(); wa.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_image_message_low_score_and_no_match_send_text_and_update_fsm():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); locked.scalar_one_or_none.return_value = customer(); db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    vision = {"type": "part", "confidence": 0.5, "description_fr": "pièce"}
    for match, expected_state in [({"found": True, "match_score": 0.3, "alternatives": [{"name": "Alt"}]}, agent.State.BROWSING), ({"found": False, "match_score": 0}, agent.State.IDLE)]:
        c = customer()
        locked.scalar_one_or_none.return_value = c
        with patch.object(agent, "analyze_whatsapp_image", new=AsyncMock(return_value=vision)), patch.object(agent, "find_best_match", new=AsyncMock(return_value=match)), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Réponse")), patch.object(agent, "_log_transition", new=AsyncMock()):
            response = await agent.handle_image_message(db, store(), c, "media-2", wa)
        assert response["reply"] == "Réponse" and c.conversation_state.get("fsm_state", agent.State.IDLE) == expected_state
    assert wa.send_text.await_count == 2


@pytest.mark.asyncio
async def test_send_post_payment_notification_success_failure_and_missing_records():
    order = SimpleNamespace(store_id=3, customer_id=7, id=10, total_amount=42)
    db = AsyncMock(); db.add = MagicMock(); store_result = MagicMock(); customer_result = MagicMock(); store_result.scalar_one_or_none.return_value = store(name="Demo", post_payment_msg="Payé"); customer_result.scalar_one_or_none.return_value = customer(conversation_state={"fsm_state": agent.State.ORDER_CREATED}); db.execute.side_effect = [store_result, customer_result, store_result, customer_result]
    with patch.object(agent, "WhatsAppClient") as client_cls:
        client = client_cls.return_value; client.send_text = AsyncMock()
        await agent.send_post_payment_notification(db, order, "paid")
        await agent.send_post_payment_notification(db, order, "failed")
    assert client.send_text.await_count == 2
    db2 = AsyncMock(); missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db2.execute.return_value = missing
    await agent.send_post_payment_notification(db2, order, "paid")


@pytest.mark.asyncio
async def test_handle_text_message_uses_cached_idle_reply_without_llm():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); c = customer(); locked.scalar_one_or_none.return_value = c; db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    with patch.object(agent, "_get_reply_cache", new=AsyncMock(return_value="cached")), patch.object(agent, "detect_intent_and_reply", new=AsyncMock()) as detect:
        reply = await agent.handle_text_message(db, store(), c, "bonjour", wa)
    assert reply == "cached" and c.last_message_at is not None
    detect.assert_not_awaited(); wa.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_text_message_product_search_updates_product_shown_state():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); c = customer(); locked.scalar_one_or_none.return_value = c; db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    products = [{"product_id": 1, "name": "Brake", "price": 10, "stock": 3, "image_url": None}]
    with patch.object(agent, "_get_reply_cache", new=AsyncMock(return_value=None)), patch.object(agent, "detect_intent_and_reply", new=AsyncMock(return_value=({"intent": "product_search", "product_query": "brake", "quantity": 1, "language": "fr"}, None))), patch.object(agent, "lookup_product_by_query", new=AsyncMock(return_value=products)), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Voici Brake")), patch.object(agent, "_log_transition", new=AsyncMock()):
        reply = await agent.handle_text_message(db, store(), c, "je cherche brake", wa)
    assert reply == "Voici Brake" and c.conversation_state["fsm_state"] == agent.State.PRODUCT_SHOWN and c.conversation_state["last_product"] == products[0]
    wa.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_text_message_cancel_resets_state_and_sends_reply():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); c = customer(conversation_state={"fsm_state": agent.State.PRODUCT_SHOWN, "last_product": {"name": "Brake"}}); locked.scalar_one_or_none.return_value = c; db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    with patch.object(agent, "_get_reply_cache", new=AsyncMock(return_value=None)), patch.object(agent, "detect_intent_and_reply", new=AsyncMock(return_value=({"intent": "order_cancel", "product_query": None, "quantity": 1, "language": "fr"}, None))), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Annulation confirmée")), patch.object(agent, "_log_transition", new=AsyncMock()):
        reply = await agent.handle_text_message(db, store(), c, "annuler", wa)
    assert reply == "Annulation confirmée" and c.conversation_state == {"fsm_state": agent.State.IDLE}


@pytest.mark.asyncio
async def test_handle_text_message_incomplete_delivery_requests_missing_fields():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); c = customer(conversation_state={"fsm_state": agent.State.AWAITING_DELIVERY, "last_product": {"name": "Brake", "price": 10}}); locked.scalar_one_or_none.return_value = c; db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    with patch.object(agent, "_get_reply_cache", new=AsyncMock(return_value=None)), patch.object(agent, "detect_intent_and_reply", new=AsyncMock(return_value=({"intent": "delivery_info", "product_query": None, "quantity": 1, "language": "fr"}, None))), patch.object(agent, "_extract_delivery_info", new=AsyncMock(return_value={"complete": False, "missing": ["adresse"]})), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Il manque votre adresse")), patch.object(agent, "_log_transition", new=AsyncMock()):
        reply = await agent.handle_text_message(db, store(), c, "Ali", wa)
    assert reply == "Il manque votre adresse" and c.conversation_state["fsm_state"] == agent.State.AWAITING_DELIVERY


@pytest.mark.asyncio
async def test_handle_text_message_product_search_without_results_uses_browsing_state():
    db = AsyncMock(); db.add = MagicMock(); locked = MagicMock(); c = customer(); locked.scalar_one_or_none.return_value = c; db.execute.return_value = locked
    wa = AsyncMock(); wa.channel = "whatsapp"
    with patch.object(agent, "_get_reply_cache", new=AsyncMock(return_value=None)), patch.object(agent, "detect_intent_and_reply", new=AsyncMock(return_value=({"intent": "product_search", "product_query": "unknown", "quantity": 1, "language": "fr"}, None))), patch.object(agent, "lookup_product_by_query", new=AsyncMock(return_value=[])), patch.object(agent, "generate_reply", new=AsyncMock(return_value="Aucun produit")), patch.object(agent, "_log_transition", new=AsyncMock()):
        reply = await agent.handle_text_message(db, store(), c, "inconnu", wa)
    assert reply == "Aucun produit" and c.conversation_state["fsm_state"] == agent.State.BROWSING


@pytest.mark.asyncio
async def test_create_order_rejects_invalid_delivery_and_insufficient_stock():
    c = customer(conversation_state={"last_product": {"product_id": 1, "price": 10, "name": "Part"}, "quantity": 1})
    db = AsyncMock(); db.add = MagicMock()
    assert await agent._create_order_from_state(db, store(), c, {"name": "A", "address": "x"}) is None
    product = SimpleNamespace(id=1, store_id=3, stock_qty=1, stock_reserved=1)
    result = MagicMock(); result.scalar_one_or_none.return_value = product; db.execute.return_value = result
    assert await agent._create_order_from_state(db, store(), c, {"name": "Ali", "address": "Tunis Centre"}) is None
    assert product.stock_reserved == 1 and db.flush.await_count == 0


@pytest.mark.asyncio
async def test_create_order_returns_none_when_product_disappears_under_lock():
    db = AsyncMock(); db.add = MagicMock(); result = MagicMock(); result.scalar_one_or_none.return_value = None; db.execute.return_value = result
    c = customer(conversation_state={"last_product": {"product_id": 99, "price": 10, "name": "Gone"}, "quantity": 1})
    assert await agent._create_order_from_state(db, store(), c, {"name": "Ali", "address": "Tunis Centre"}) is None
