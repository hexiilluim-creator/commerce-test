from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services import social_agent
from services.tenant_access import TenantAccessState, get_tenant_access_state, is_tenant_active


def run(coro):
    return asyncio.run(coro)


def test_tenant_access_dataclass_defaults_are_explicit():
    state = TenantAccessState(is_tenant_active=True, billing_status="active")
    assert state.is_tenant_active is True
    assert state.billing_status == "active"
    assert state.suspended_reason is None


def test_tenant_access_missing_store_fails_closed():
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = AsyncMock()
    db.execute.return_value = result
    state = run(get_tenant_access_state(db, 404))
    assert state == TenantAccessState(False, "unknown", "tenant_not_found")
    assert run(is_tenant_active(db, 404)) is False
    assert db.execute.await_count == 2


def test_tenant_access_active_store_preserves_billing_state():
    store = SimpleNamespace(is_active=True, billing_status="past_due", suspended_reason=None)
    result = SimpleNamespace(scalar_one_or_none=lambda: store)
    db = AsyncMock()
    db.execute.return_value = result
    state = run(get_tenant_access_state(db, 7))
    assert state.is_tenant_active is True
    assert state.billing_status == "past_due"
    assert state.suspended_reason is None
    assert run(is_tenant_active(db, 7)) is True


def test_tenant_access_database_error_fails_closed():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("database unavailable")
    state = run(get_tenant_access_state(db, 7))
    assert state == TenantAccessState(False, "unavailable", "tenant_state_unavailable")


def test_social_message_without_store_is_dropped():
    result = run(social_agent.handle_social_message(0, "facebook", "sender", "hello"))
    assert result == {"status": "dropped", "reason": "store_id_not_resolved"}


def test_social_sync_wrapper_ignores_missing_identity():
    assert social_agent.handle_social_message_sync(None, "instagram", "sender", "hello") is None
    assert social_agent.handle_social_message_sync(1, "instagram", None, "hello") is None
