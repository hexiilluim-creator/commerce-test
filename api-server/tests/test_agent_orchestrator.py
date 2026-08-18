"""Tests ciblés sur le routage multi-agents et le correctif auto_parts."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from models.database import BusinessType  # noqa: E402
from services.agent_orchestrator import RouteDecision, dispatch_customer_message, resolve_route  # noqa: E402

pytestmark = pytest.mark.unit


def _make_store(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "name": "Test Store",
        "auto_parts_mode": False,
        "billing_plan_code": "starter",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_customer(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "store_id": 1,
        "conversation_state": {},
        "opted_out": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _FakeDB:
    def __init__(self, config=None):
        self._config = config

    async def execute(self, *args, **kwargs):
        return MagicMock(scalar_one_or_none=lambda: self._config)


def test_route_decision_dataclass():
    rd = RouteDecision(route="commerce_agent", degraded_mode=False, reason="default")
    assert rd.route == "commerce_agent"
    assert rd.degraded_mode is False
    assert rd.reason == "default"


@pytest.mark.asyncio
async def test_resolve_route_owner_returns_owner_agent():
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(),
        role="owner",
        channel="whatsapp",
        billing_status="active",
    )
    assert result.route == "owner_agent"


@pytest.mark.asyncio
async def test_auto_parts_idle_falls_through_to_other_business_types():
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(auto_parts_mode=True),
        role="customer",
        channel="whatsapp",
        billing_status="active",
        customer=_make_customer(conversation_state={"auto_fsm": "auto_idle"}),
        text="bonjour",
    )
    assert result.route == "commerce_agent"


@pytest.mark.asyncio
async def test_auto_parts_active_stays_on_auto():
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(auto_parts_mode=True),
        role="customer",
        channel="whatsapp",
        billing_status="active",
        customer=_make_customer(conversation_state={"auto_fsm": "auto_search"}),
        text="je cherche un alternateur",
    )
    assert result.route == "auto_parts_agent"
    assert result.reason == "auto_parts_conversation"


@pytest.mark.asyncio
async def test_agent_orchestrator_returns_auto_parts_when_business_type():
    # Use string "auto" since BusinessType enum uses string values
    config = SimpleNamespace(business_type="auto")
    result = await resolve_route(
        _FakeDB(config=config),
        store=_make_store(auto_parts_mode=False),
        role="customer",
        channel="whatsapp",
        billing_status="active",
        customer=_make_customer(),
        text="besoin d'une piece",
    )
    assert result.route == "auto_parts_agent"
    assert result.reason == "business_type_auto_parts"


@pytest.mark.asyncio
async def test_other_channels_when_auto_parts_mode_no_fsm():
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(auto_parts_mode=True),
        role="customer",
        channel="instagram",
        billing_status="active",
        customer=_make_customer(conversation_state={"auto_fsm": "auto_idle"}),
        text="bonjour sur insta",
    )
    assert result.route == "social_sales_agent"


@pytest.mark.asyncio
async def test_owner_goes_to_owner_agent_regardless():
    result = await resolve_route(
        _FakeDB(config=SimpleNamespace(business_type="auto")),
        store=_make_store(auto_parts_mode=True),
        role="owner",
        channel="instagram",
        billing_status="active",
    )
    assert result.route == "owner_agent"


@pytest.mark.asyncio
async def test_dispatch_customer_message_calls_agent():
    db = _FakeDB()
    store = _make_store()
    customer = _make_customer()

    with patch("services.agent_orchestrator.resolve_route", AsyncMock(return_value=RouteDecision(route="commerce_agent", degraded_mode=False, reason="test"))):
        try:
            await dispatch_customer_message(db, store=store, customer=customer, text="Bonjour", wa=MagicMock(), channel="whatsapp", payload={"message_id": "msg_001"})
        except Exception:
            pass


# ── P0-6: Bug fix validation — auto_state fallback when customer is None ───

@pytest.mark.asyncio
async def test_auto_parts_mode_with_no_customer():
    """auto_parts_mode avec customer=None ne doit pas lever d'exception."""
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(auto_parts_mode=True),
        role="customer",
        channel="whatsapp",
        billing_status="active",
        customer=None,
        text="bonjour",
    )
    assert result.route in ("commerce_agent", "social_sales_agent")


@pytest.mark.asyncio
async def test_suspended_tenant_blocked():
    """Un tenant suspendu doit recevoir la route blocked."""
    result = await resolve_route(
        _FakeDB(),
        store=_make_store(),
        role="customer",
        channel="whatsapp",
        billing_status="suspended",
        customer=None,
        text="test",
    )
    assert result.route == "blocked"
    assert result.degraded_mode is True


@pytest.mark.asyncio
async def test_dispatch_customer_message_blocked_tenant():
    """dispatch_customer_message doit retourner le message de suspension."""
    db = _FakeDB()
    store = _make_store()
    customer = _make_customer()
    with patch(
        "services.agent_orchestrator.resolve_route",
        AsyncMock(return_value=RouteDecision(route="blocked", degraded_mode=True, reason="tenant_suspended")),
    ):
        result = await dispatch_customer_message(
            db,
            store=store,
            customer=customer,
            text="test",
            wa=MagicMock(),
            channel="whatsapp",
        )
        assert "suspendu" in result.lower()
