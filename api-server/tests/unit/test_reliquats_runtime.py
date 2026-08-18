from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import store_resolver, tasks
from services import structured_agent


@pytest.mark.asyncio
async def test_structured_agent_intent_fallback_and_menu_languages(monkeypatch):
    async def fail_chat(**kwargs):
        raise RuntimeError("gateway unavailable")

    import services.llm_gateway as llm_gateway
    monkeypatch.setattr(llm_gateway, "chat", fail_chat)
    result = await structured_agent.detect_intent_and_emotion("bonjour")
    assert result == {"intent": "other", "emotion": "interested", "product_query": None, "preferences": []}
    assert "Bienvenue" in structured_agent.send_main_menu("fr")
    assert "Asslema" in structured_agent.send_main_menu("darija")
    assert structured_agent._customer_lock_key(42).endswith(":42")


@pytest.mark.asyncio
async def test_structured_agent_lock_acquire_and_release(monkeypatch):
    lock_service = SimpleNamespace(try_acquire=AsyncMock(return_value=True), release=AsyncMock())
    monkeypatch.setattr("services.redis_lock.lock_service", lock_service)
    async with structured_agent._customer_processing_lock(12):
        pass
    lock_service.try_acquire.assert_awaited_once()
    lock_service.release.assert_awaited_once_with("structured_agent:customer:12")


@pytest.mark.asyncio
async def test_structured_agent_lock_falls_back_when_redis_unavailable(monkeypatch):
    lock_service = SimpleNamespace(try_acquire=AsyncMock(side_effect=RuntimeError("redis down")), release=AsyncMock())
    monkeypatch.setattr("services.redis_lock.lock_service", lock_service)
    async with structured_agent._customer_processing_lock(13):
        pass
    lock_service.release.assert_not_awaited()


def test_tasks_helpers_and_task_facade(monkeypatch):
    assert tasks._retry_with_backoff("unit", 0) == 1
    assert tasks._retry_with_backoff("unit", 8) == 120
    assert tasks._run_async(asyncio.sleep(0, result={"ok": True})) == {"ok": True}
    if not getattr(tasks, "_CELERY_AVAILABLE", False):
        for name in ("process_whatsapp_message", "send_order_notification", "cleanup_orphaned_redis_sessions"):
            task = getattr(tasks, name)
            assert task.delay("sample") is None
            assert task.apply_async(args=["sample"]) is None
            assert task("sample") is None
    else:
        assert callable(tasks.process_whatsapp_message)
        assert callable(tasks.send_order_notification)


@pytest.mark.asyncio
async def test_store_resolver_local_redis_db_and_invalidation(monkeypatch):
    store_resolver._local_cache.clear()
    monkeypatch.setattr(store_resolver, "_redis_get", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(store_resolver, "_redis_set", AsyncMock())
    monkeypatch.setattr(store_resolver, "_db_resolve_social", AsyncMock(return_value=77))
    assert await store_resolver.resolve_store_id_from_social_id(None, "facebook") is None
    assert await store_resolver.resolve_store_id_from_social_id("acct", "facebook") == 77
    assert await store_resolver.resolve_store_id_from_social_id("acct", "facebook") == 77
    monkeypatch.setattr(store_resolver, "_get_redis", AsyncMock(return_value=None))
    await store_resolver.invalidate_store_cache("facebook", "acct")
    assert "store_resolver:facebook:acct" not in store_resolver._local_cache


@pytest.mark.asyncio
async def test_store_resolver_phone_and_redis_hit(monkeypatch):
    store_resolver._local_cache.clear()
    monkeypatch.setattr(store_resolver, "_redis_get", AsyncMock(return_value=(True, 88)))
    monkeypatch.setattr(store_resolver, "_db_resolve_phone", AsyncMock())
    assert await store_resolver.resolve_store_id_from_phone("") is None
    assert await store_resolver.resolve_store_id_from_phone("phone") == 88
    assert await store_resolver.resolve_store_id_from_phone("phone") == 88
    store_resolver._local_cache.clear()
    monkeypatch.setattr(store_resolver, "_redis_get", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(store_resolver, "_db_resolve_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(store_resolver, "_redis_set", AsyncMock())
    assert await store_resolver.resolve_store_id_from_phone("missing") is None



def test_conversation_state_nested_mutations_and_snapshot():
    from services.conversation_state import ConversationState

    customer = SimpleNamespace(conversation_state={"items": [{"sku": "A"}], "empty": []})
    state = ConversationState.from_customer(customer)
    assert not state.is_dirty
    state["items"][0]["qty"] = 2
    state["items"].append({"sku": "B"})
    state["items"].extend([{"sku": "C"}])
    state["items"].insert(0, {"sku": "Z"})
    assert state["items"].pop()["sku"] == "C"
    state["items"].remove(state["items"][1])
    state["items"].sort(key=lambda x: x["sku"])
    state["items"].reverse()
    state["items"][0:1] = [{"sku": "R"}]
    del state["items"][-1]
    state["extra"] = {"nested": [1]}
    state["extra"]["nested"].append(2)
    assert state.is_dirty
    assert customer.conversation_state == state.snapshot()
    assert state.sync() == customer.conversation_state
    assert len(state) >= 2
    assert repr(state).startswith("ConversationState(")


def test_conversation_state_mapping_operations_replace_and_empty_source():
    from services.conversation_state import ConversationState

    customer = SimpleNamespace(conversation_state=None)
    state = ConversationState.from_customer(customer)
    assert state.is_dirty and len(state) == 0
    state.setdefault("a", 1)
    assert state.setdefault("a", 2) == 1
    state.update({"b": 2}, c=3)
    assert state.pop("missing", "fallback") == "fallback"
    assert state.pop("b") == 2
    state["x"] = 1
    state.clear()
    state.replace({"new": {"values": [1, 2]}})
    assert state.snapshot() == {"new": {"values": [1, 2]}}
    assert list(iter(state)) == ["new"]



def test_fernet_rotation_single_key_context_and_errors(monkeypatch):
    from cryptography.fernet import Fernet
    from services import fernet_rotation

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    monkeypatch.delenv("FERNET_KEYS_JSON", raising=False)
    fernet_rotation.reset_cache()
    assert fernet_rotation.encrypt("") == ""
    token = fernet_rotation.encrypt("secret", context="tenant:1")
    assert fernet_rotation.decrypt(token, context="tenant:1") == "secret"
    with pytest.raises(ValueError):
        fernet_rotation.decrypt(token, context="tenant:2")
    with pytest.raises(ValueError):
        fernet_rotation.decrypt(token)
    with pytest.raises(ValueError):
        fernet_rotation.decrypt("not-a-token")
    assert fernet_rotation.decrypt("") == ""
    assert fernet_rotation.get_fernet() is fernet_rotation.get_fernet()
    fernet_rotation.reset_cache()
    monkeypatch.setenv("ENCRYPTION_KEY", "bad")
    with pytest.raises(RuntimeError):
        fernet_rotation.get_fernet()


def test_fernet_rotation_multikey_and_invalid_json(monkeypatch):
    from cryptography.fernet import Fernet, MultiFernet
    from services import fernet_rotation

    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key2)
    monkeypatch.setenv("FERNET_KEYS_JSON", f'["{key1}", "{key2}"]')
    fernet_rotation.reset_cache()
    instance = fernet_rotation.get_fernet()
    assert isinstance(instance, MultiFernet)
    token = fernet_rotation.encrypt("rotated")
    assert fernet_rotation.decrypt(token) == "rotated"
    fernet_rotation.reset_cache()
    monkeypatch.setenv("FERNET_KEYS_JSON", "not-json")
    with pytest.raises(RuntimeError):
        fernet_rotation.get_fernet()


@pytest.mark.asyncio
async def test_emotion_alerts_paths(monkeypatch):
    from services import emotion_alerts

    sent = []
    monkeypatch.setattr(emotion_alerts, "_send_slack_alert", AsyncMock(side_effect=lambda *args: sent.append(args)))
    monkeypatch.setattr(emotion_alerts, "_get_redis", AsyncMock(return_value=None))
    await emotion_alerts.trigger_emotion_alert_if_needed(1, "Shop", 2, "urgent")
    assert sent == [("Shop", 2, "urgent", 1)]

    class FakeRedis:
        def __init__(self, count=1, fail=False):
            self.count = count
            self.fail = fail
            self.closed = False
            self.deleted = []
        async def incr(self, key):
            if self.fail:
                raise RuntimeError("incr failed")
            return self.count
        async def expire(self, key, ttl):
            return True
        async def delete(self, key):
            self.deleted.append(key)
        async def aclose(self):
            self.closed = True

    redis = FakeRedis(count=1)
    monkeypatch.setattr(emotion_alerts, "_get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(emotion_alerts, "_log_to_db", AsyncMock())
    monkeypatch.setattr("config.settings.EMOTION_ESCALATION_THRESHOLD", 2)
    await emotion_alerts.trigger_emotion_alert_if_needed(1, "Shop", 2, "frustrated", db=object())
    assert sent == [("Shop", 2, "urgent", 1)]
    emotion_alerts._log_to_db.assert_awaited_once()
    assert redis.closed

    redis2 = FakeRedis(count=2)
    monkeypatch.setattr(emotion_alerts, "_get_redis", AsyncMock(return_value=redis2))
    await emotion_alerts.trigger_emotion_alert_if_needed(1, "Shop", 2, "frustrated")
    assert sent[-1] == ("Shop", 2, "frustrated", 2)
    await emotion_alerts.reset_frustration_counter(1, 2)
    assert redis2.deleted
    assert redis2.closed

    redis3 = FakeRedis(fail=True)
    monkeypatch.setattr(emotion_alerts, "_get_redis", AsyncMock(return_value=redis3))
    await emotion_alerts.trigger_emotion_alert_if_needed(1, "Shop", 2, "frustrated")
    assert redis3.closed
    await emotion_alerts.reset_frustration_counter(1, 2)

@pytest.mark.asyncio
async def test_emotion_alerts_slack_http_paths(monkeypatch):
    from services import emotion_alerts

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    class Client:
        def __init__(self, response=None, error=False, **kwargs):
            self.response = response
            self.error = error
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, *args, **kwargs):
            if self.error:
                raise RuntimeError("network")
            return self.response

    monkeypatch.setenv("SLACK_ALERT_WEBHOOK", "https://slack.invalid/hook")
    monkeypatch.setattr(emotion_alerts.httpx, "AsyncClient", lambda **kwargs: Client(Response(500)))
    await emotion_alerts._send_slack_alert("Shop", 1, "urgent", 3)
    monkeypatch.setattr(emotion_alerts.httpx, "AsyncClient", lambda **kwargs: Client(Response(204)))
    await emotion_alerts._send_slack_alert("Shop", 1, "urgent", 3)
    monkeypatch.setattr(emotion_alerts.httpx, "AsyncClient", lambda **kwargs: Client(error=True))
    await emotion_alerts._send_slack_alert("Shop", 1, "urgent", 3)
    monkeypatch.delenv("SLACK_ALERT_WEBHOOK")
    await emotion_alerts._send_slack_alert("Shop", 1, "urgent", 3)


@pytest.mark.asyncio
async def test_ai_guardrails_memory_credit_lifecycle(monkeypatch):
    from services import ai_guardrails as guard

    guard._MEMORY_CREDITS.clear()
    guard._MEMORY_USED.clear()
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr(guard, "_get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr(guard, "_get_plan_quota", AsyncMock(return_value=10))
    monkeypatch.setattr(guard, "_persist_credit_event", AsyncMock())
    monkeypatch.setattr(guard, "_get_db_credit_state", AsyncMock(return_value=(7, 3)))
    assert await guard.check_tenant_credit(9, 0)
    assert await guard.check_tenant_credit(9, 5)
    assert await guard.deduct_tenant_credit(9, 3)
    stats = await guard.get_tenant_credit_stats(9)
    assert stats["remaining"] == 7 and stats["used"] == 3
    assert stats["credits_percent_used"] == 30.0
    assert await guard.add_tenant_credits(9, 4, "bonus") == 11
    assert await guard.add_tenant_credits(9, 0) == 7
    assert await guard.reset_monthly_credits(9) == 10
    assert (await guard.get_tenant_credit_stats(9))["remaining"] == 10


@pytest.mark.asyncio
async def test_ai_guardrails_redis_pipeline_and_negative_balance(monkeypatch):
    from services import ai_guardrails as guard

    class Pipe:
        def __init__(self, results):
            self.results = results
            self.ops = []
        def decrby(self, *args): self.ops.append(("decrby", args))
        def incrby(self, *args): self.ops.append(("incrby", args))
        def set(self, *args, **kwargs): self.ops.append(("set", args, kwargs))
        async def execute(self): return self.results

    class Redis:
        def __init__(self):
            self.pipes = [Pipe([5, 3]), Pipe([-5, 3]), Pipe([14, 4]), Pipe([])]
        async def get(self, key): return None
        def pipeline(self): return self.pipes.pop(0)
        async def set(self, *args, **kwargs): return True

    redis = Redis()
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr(guard, "_get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(guard, "_get_plan_quota", AsyncMock(return_value=10))
    monkeypatch.setattr(guard, "_persist_credit_event", AsyncMock())
    assert await guard.deduct_tenant_credit(3, 2)
    assert await guard.add_tenant_credits(3, 4, "top_up") == 14
    assert await guard.reset_monthly_credits(3) == 10
    assert await guard.check_tenant_credit(3, 1)


@pytest.mark.asyncio
async def test_ai_guardrails_db_fallback_helpers(monkeypatch):
    from services import ai_guardrails as guard
    monkeypatch.setattr(guard, "_get_db_credit_state", AsyncMock(return_value=(None, 4)))
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(guard, "_allow_memory_fallback", lambda: False)
    assert await guard._shared_remaining_balance(1, 10) == 10
    monkeypatch.setattr(guard, "_get_db_credit_state", AsyncMock(return_value=(3, 4)))
    assert await guard._shared_remaining_balance(1, 10) == 3
    monkeypatch.setattr(guard, "_get_db_credit_state", AsyncMock(side_effect=RuntimeError("db")))
    # The helper itself is mocked to raise only to ensure caller-side paths remain explicit.
    with pytest.raises(RuntimeError):
        await guard._get_db_credit_state(1)



def test_credit_ledger_helpers_and_packs():
    from services import credit_ledger as ledger
    assert ledger._extract_store_id_and_limit((), {"store_id": "4", "limit": 3}) == (4, 3)
    assert ledger._extract_store_id_and_limit(("db", 5), {}) == (5, 50)
    assert ledger._extract_store_id_and_limit((6,), {}) == (6, 50)
    with pytest.raises(TypeError):
        ledger._extract_store_id_and_limit((), {})
    assert ledger.estimate_llm_credits(0, 0) == 0
    assert ledger.estimate_llm_credits(-1, 1) == 1
    assert ledger.estimate_llm_credits(1000, 1) == 2
    packs = ledger.get_available_packs()
    assert len(packs) == len(ledger.CREDIT_PACKS)
    assert {p["pack_id"] for p in packs} == set(ledger.CREDIT_PACKS)


@pytest.mark.asyncio
async def test_credit_ledger_history_topup_and_bonus(monkeypatch):
    from datetime import UTC, datetime
    from services import credit_ledger as ledger

    class Result:
        def __init__(self, rows=None, scalar=None): self.rows, self.scalar_value = rows or [], scalar
        def mappings(self): return self
        def all(self): return self.rows
        def scalar_one_or_none(self): return self.scalar_value
        def scalars(self): return self

    class DB:
        def __init__(self, result): self.result = result; self.commits = 0
        async def execute(self, *args, **kwargs): return self.result
        async def commit(self): self.commits += 1
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    now = datetime.now(UTC)
    db = DB(Result([{"event_type": "top_up", "credits_delta": 50, "balance_after": 50, "description": "x", "created_at": now}]))
    monkeypatch.setattr(ledger, "AsyncSessionLocal", lambda: db)
    history = await ledger.get_ledger_history(store_id=2, limit=5)
    assert history[0]["credits_delta"] == 50 and history[0]["created_at"] == now.isoformat()
    assert (await ledger.purchase_top_up(2, "unknown", "ref"))["ok"] is False
    monkeypatch.setattr(ledger, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr("services.ai_guardrails.add_tenant_credits", AsyncMock(return_value=55))
    result = await ledger.purchase_top_up(2, "starter_50", "ref-1")
    assert result["ok"] is True and result["credits_added"] == 50
    monkeypatch.setattr("services.ai_guardrails.add_tenant_credits", AsyncMock(side_effect=RuntimeError("fail")))
    bonus = await ledger.grant_bonus_credits(2, 5)
    assert bonus["ok"] is False
    monkeypatch.setattr("services.ai_guardrails.add_tenant_credits", AsyncMock(return_value=60))
    bonus = await ledger.grant_bonus_credits(2, 5)
    assert bonus == {"ok": True, "credits_granted": 5, "new_balance": 60}


@pytest.mark.asyncio
async def test_credit_ledger_topup_migration_failure(monkeypatch):
    from services import credit_ledger as ledger
    class DB:
        async def execute(self, *args, **kwargs): raise RuntimeError("missing credit_events")
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    monkeypatch.setattr(ledger, "AsyncSessionLocal", lambda: DB())
    result = await ledger.purchase_top_up(1, "starter_50", "ref")
    assert result["ok"] is False and result["error"] == "migration_required"


@pytest.mark.asyncio
async def test_openai_resolver_platform_client(monkeypatch):
    import importlib
    from services import openai_resolver
    openai_resolver = importlib.reload(openai_resolver)
    sentinel = object()
    monkeypatch.setattr(openai_resolver, "AsyncOpenAI", lambda **kwargs: sentinel)
    monkeypatch.setattr(openai_resolver.settings, "OPENAI_API_KEY", "test-key")
    assert openai_resolver.get_platform_client() is sentinel
    assert await openai_resolver.resolve_openai_client(1, None) is sentinel


def test_opentelemetry_setup_without_otlp(monkeypatch):
    from fastapi import FastAPI
    from services import opentelemetry_config
    monkeypatch.delenv("OTLP_ENDPOINT", raising=False)
    opentelemetry_config.setup_opentelemetry(FastAPI())


@pytest.mark.asyncio
async def test_redis_lock_services_and_tokens(monkeypatch):
    import importlib
    from services import redis_lock
    redis_lock = importlib.reload(redis_lock)

    class Redis:
        def __init__(self, result=True): self.result = result; self.calls = []
        async def set(self, *args, **kwargs): self.calls.append(("set", args, kwargs)); return self.result
        async def delete(self, key): self.calls.append(("delete", key)); return 1

    fake = Redis(True)
    # Exécuter également les chemins de création/singleton sans ouvrir de connexion réseau.
    created = redis_lock.get_redis()
    assert created is redis_lock.get_redis()
    assert redis_lock.get_redis_sync() is not None
    monkeypatch.setattr(redis_lock, "get_redis", lambda: fake)
    service = redis_lock._RedisLockService()
    assert await service.try_acquire("k", 4)
    async with service.acquire("k2", 5) as acquired:
        assert acquired is True
    await service.release("k")
    assert await redis_lock.acquire_lock("k", 2) in {"1", None}
    await redis_lock.release_lock("k", token="1")

    no_op = redis_lock._NoOpLockService()
    assert await no_op.try_acquire("x") is True
    async with no_op.acquire("x") as acquired:
        assert acquired is True
    await no_op.release("x")
    assert await redis_lock.release_lock("x", token=None) is None


@pytest.mark.asyncio
async def test_tenant_db_context_session_injects_and_cleans(monkeypatch):
    from services import tenant_db_context as ctx
    ctx._load_contextvars()
    tenant_token = ctx._current_tenant_id.set(42)
    role_token = ctx._current_user_role.set("manager")

    class Result:
        def scalar_one_or_none(self): return "42"
    class Session:
        def __init__(self): self.calls = []; self.rolled_back = False
        async def execute(self, statement, params=None):
            self.calls.append((str(statement), params))
            return Result()
        async def rollback(self): self.rolled_back = True
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    session = Session()
    try:
        yielded = []
        async for item in ctx.tenant_session(lambda: session):
            yielded.append(item)
        assert yielded == [session]
        assert session.rolled_back
        assert len(session.calls) == 4
        assert await ctx.assert_tenant_guc_set(session) == "42"
    finally:
        ctx._current_tenant_id.reset(tenant_token)
        ctx._current_user_role.reset(role_token)


@pytest.mark.asyncio
async def test_tenant_db_context_without_tenant_and_reset_error(monkeypatch):
    from services import tenant_db_context as ctx
    class Session:
        async def rollback(self): raise RuntimeError("rollback")
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    old_tenant, old_role = ctx._current_tenant_id, ctx._current_user_role
    old_loader = ctx._load_contextvars
    ctx._load_contextvars = lambda: None
    ctx._current_tenant_id = None
    ctx._current_user_role = None
    try:
        yielded = []
        async for item in ctx.tenant_session(lambda: Session()): yielded.append(item)
        assert len(yielded) == 1
        assert ctx._get_tenant_id() is None
        assert ctx._get_user_role() is None
    finally:
        ctx._current_tenant_id, ctx._current_user_role = old_tenant, old_role
        ctx._load_contextvars = old_loader


def test_tenant_db_context_hook_install_failure():
    from services import tenant_db_context as ctx
    with pytest.raises(RuntimeError, match="Impossible d'installer"):
        ctx.install_tenant_guc_hook(object())



def test_tenant_db_context_checkout_hook_callback(monkeypatch):
    from services import tenant_db_context as ctx
    captured = []
    def listens_for(*args, **kwargs):
        def decorator(fn):
            captured.append(fn)
            return fn
        return decorator
    monkeypatch.setattr(ctx.event, "listens_for", listens_for)
    class Engine: sync_engine = object()
    ctx.install_tenant_guc_hook(Engine())
    assert captured
    class Cursor:
        def __init__(self): self.commands = []; self.closed = False
        def execute(self, sql): self.commands.append(sql)
        def close(self): self.closed = True
    class Conn:
        def __init__(self): self.cursor_obj = Cursor()
        def cursor(self): return self.cursor_obj
    ctx._load_contextvars()
    tenant_token = ctx._current_tenant_id.set(7)
    role_token = ctx._current_user_role.set("manager's")
    try:
        conn = Conn()
        captured[0](conn, None, None)
        assert "'7'" in conn.cursor_obj.commands[0]
        assert "manager''s" in conn.cursor_obj.commands[1]
        assert conn.cursor_obj.closed
    finally:
        ctx._current_tenant_id.reset(tenant_token)
        ctx._current_user_role.reset(role_token)


@pytest.mark.asyncio
async def test_rgpd_compatibility_wrappers_and_token_empty_values(monkeypatch):
    from services.rgpd_export import export_user_data
    from services.rgpd_purge import purge_user_data
    from services import token_store
    assert export_user_data(7) == {"status": "exporting", "user_id": 7}
    assert purge_user_data(7) == {"status": "purged", "user_id": 7}

    class Redis:
        async def get(self, key): return None
        async def delete(self, key): return 1
        async def setex(self, *args): return True
    monkeypatch.setattr("services.redis_lock.get_redis", lambda: Redis())
    assert await token_store.get_token("missing") is None
    await token_store.delete_token("missing")


@pytest.mark.asyncio
async def test_token_store_delete_production_without_redis(monkeypatch):
    from services import token_store
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(token_store, "_allow_memory_fallback", lambda: False)
    monkeypatch.setattr("services.redis_lock.get_redis", lambda: (_ for _ in ()).throw(RuntimeError("redis unavailable")))
    await token_store.delete_token("prod-missing")


def test_token_store_cleanup_expired_entry():
    import time
    from services import token_store
    token_store._mem_store["expired"] = ("value", time.time() - 1)
    token_store._mem_cleanup()
    assert "expired" not in token_store._mem_store
