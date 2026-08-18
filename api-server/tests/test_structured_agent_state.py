from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models.database import Customer
from services.conversation_state import ConversationState

# AUDIT FIX (drift majeur détecté par audit outillé) : ce fichier remplaçait
# sys.modules["services.ai_agent"] (et 4 autres modules) par des stubs
# légers, PERMANENTS, jamais restaurés. Comme services.structured_agent fait
# `from services.ai_agent import _check_timeout, _log_transition` (liaison
# précoce), le stub n'est nécessaire QUE pendant cet import — après quoi
# structured_agent a sa propre référence locale au lambda stub. Mais laisser
# le stub en place dans sys.modules polluait ensuite TOUT test exécuté après
# celui-ci dans la même session pytest : tout `from services.ai_agent import
# _check_timeout` ailleurs (ex: tests/test_ai_agent_fsm.py) récupérait le
# lambda `lambda *_args, **_kwargs: False` au lieu de la vraie fonction,
# causant des échecs `assert False is True` sans rapport avec le code réel.
# Fix : sauvegarder les modules originaux et les restaurer juste après
# l'import de structured_agent.
_ORIGINAL_MODULES = {
    name: sys.modules.get(name)
    for name in (
        "services.ai_agent",
        "services.embedding_search",
        "utils.llm_parser",
        "utils.whatsapp_client",
        "services.celery_app",
    )
}

_ai_agent_stub = types.ModuleType("services.ai_agent")

async def _noop_log_transition(*_args, **_kwargs):
    return None

_ai_agent_stub._check_timeout = lambda *_args, **_kwargs: False
_ai_agent_stub._log_transition = _noop_log_transition
sys.modules["services.ai_agent"] = _ai_agent_stub

_embedding_stub = types.ModuleType("services.embedding_search")

async def _stub_search_products(*_args, **_kwargs):
    return []

_embedding_stub.search_products = _stub_search_products
sys.modules["services.embedding_search"] = _embedding_stub

_llm_parser_stub = types.ModuleType("utils.llm_parser")
_llm_parser_stub.parse_llm_json = lambda *_args, **_kwargs: {}
sys.modules["utils.llm_parser"] = _llm_parser_stub

_whatsapp_stub = types.ModuleType("utils.whatsapp_client")

class _StubWhatsAppClient:
    channel = "whatsapp"

_whatsapp_stub.WhatsAppClient = _StubWhatsAppClient
sys.modules["utils.whatsapp_client"] = _whatsapp_stub

_celery_stub = types.ModuleType("services.celery_app")

class _StubCeleryApp:
    def task(self, *args, **kwargs):
        def _decorator(fn):
            return fn
        return _decorator

_celery_stub.celery_app = _StubCeleryApp()
sys.modules["services.celery_app"] = _celery_stub

structured_agent = importlib.import_module("services.structured_agent")

# Restaure immédiatement les vrais modules : structured_agent a déjà résolu
# `_check_timeout`/`_log_transition` sur ses propres attributs de module au
# moment de l'import ci-dessus, donc la restauration ne change rien à son
# comportement mais évite de polluer le reste de la session pytest.
for _name, _mod in _ORIGINAL_MODULES.items():
    if _mod is not None:
        sys.modules[_name] = _mod
    else:
        sys.modules.pop(_name, None)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, customer):
        self.customer = customer
        self.commit_calls = 0
        self.added = []

    async def execute(self, _stmt):
        return _FakeResult(self.customer)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


class _FakeWA:
    channel = "whatsapp"

    def __init__(self):
        self.sent = []

    async def send_text(self, phone, text):
        self.sent.append((phone, text))


class _FakeLockService:
    def __init__(self):
        self._held: set[str] = set()

    async def try_acquire(self, key: str, timeout: int = 30) -> bool:
        if key in self._held:
            return False
        self._held.add(key)
        return True

    async def release(self, key: str) -> None:
        self._held.discard(key)


@pytest.mark.asyncio
async def test_conversation_state_marks_dirty_on_nested_mutations():
    customer = SimpleNamespace(conversation_state={"fsm_state": structured_agent.IDLE, "history": []})

    state = ConversationState.from_customer(customer)
    history = state.setdefault("history", [])
    history.append("msg-1")
    state["fsm_state"] = structured_agent.MAIN_MENU

    assert state.is_dirty is True
    assert customer.conversation_state == {
        "fsm_state": structured_agent.MAIN_MENU,
        "history": ["msg-1"],
    }


@pytest.mark.asyncio
async def test_handle_main_menu_updates_customer_state_without_manual_writeback():
    customer = SimpleNamespace(conversation_state={"fsm_state": structured_agent.MAIN_MENU, "last_lang": "fr"})
    state = ConversationState.from_customer(customer)

    reply = await structured_agent.handle_main_menu(
        db=None,
        store=SimpleNamespace(),
        customer=customer,
        analysis={"intent": "product_search"},
        message="je cherche un produit",
        state=state,
    )

    assert customer.conversation_state["fsm_state"] == structured_agent.BROWSING
    assert "Que recherchez-vous" in reply


@pytest.mark.asyncio
async def test_handle_message_serializes_concurrent_updates_per_customer(monkeypatch):
    import services.redis_lock as redis_lock

    customer = Customer(
        id=42,
        store_id=7,
        whatsapp_phone="+21699000042",
        name="Client Test",
        conversation_state={"fsm_state": structured_agent.MAIN_MENU, "history": []},
        preferences={},
        language="fr",
    )
    store = SimpleNamespace(
        id=7,
        name="Store Test",
        conversation_timeout_min=30,
        payment_config=None,
        onboarding_completed=False,
    )
    wa_client = _FakeWA()
    db1 = _FakeDB(customer)
    db2 = _FakeDB(customer)

    async def _fake_detect(_message: str) -> dict:
        return {
            "intent": "other",
            "emotion": "interested",
            "product_query": None,
            "preferences": [],
            "detected_language": "fr",
        }

    async def _fake_route(db, store, customer, analysis, message, wa_client, state=None):
        state = state or ConversationState.from_customer(customer)
        history_snapshot = list(state.get("history", []))
        await asyncio.sleep(0.05 if message == "first" else 0.01)
        history_snapshot.append(message)
        state["history"] = history_snapshot
        state["fsm_state"] = structured_agent.BROWSING
        return f"ok:{message}"

    monkeypatch.setattr(redis_lock, "lock_service", _FakeLockService())
    monkeypatch.setattr(structured_agent, "detect_intent_and_emotion", _fake_detect)
    monkeypatch.setattr(structured_agent, "route", _fake_route)
    monkeypatch.setattr(structured_agent, "_check_timeout", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(structured_agent, "_log_transition", AsyncMock())

    task1 = asyncio.create_task(structured_agent.handle_message(db1, store, customer, "first", wa_client))
    await asyncio.sleep(0.01)
    task2 = asyncio.create_task(structured_agent.handle_message(db2, store, customer, "second", wa_client))

    replies = await asyncio.gather(task1, task2)

    assert replies == ["ok:first", "ok:second"]
    assert customer.conversation_state["history"] == ["first", "second"]
    assert customer.conversation_state["fsm_state"] == structured_agent.BROWSING
    assert db1.commit_calls == 1
    assert db2.commit_calls == 1
    assert [text for _, text in wa_client.sent] == ["ok:first", "ok:second"]
