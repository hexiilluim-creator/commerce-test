from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import tenant_db_context as tdc


@pytest.fixture(autouse=True)
def reset_lazy_contextvars():
    old_tenant, old_role = tdc._current_tenant_id, tdc._current_user_role
    tdc._current_tenant_id = None
    tdc._current_user_role = None
    yield
    tdc._current_tenant_id, tdc._current_user_role = old_tenant, old_role


def test_contextvars_load_and_return_values():
    tenant = ContextVar("test_tenant", default=None)
    role = ContextVar("test_role", default=None)
    with patch("middleware.tenant.current_tenant_id", tenant), patch(
        "middleware.tenant.current_user_role", role
    ):
        tenant.set(17)
        role.set("admin")
        assert tdc._get_tenant_id() == 17
        assert tdc._get_user_role() == "admin"


def test_contextvars_return_none_when_context_module_unavailable():
    with patch("builtins.__import__", side_effect=ImportError("not available")):
        tdc._load_contextvars()
    assert tdc._get_tenant_id() is None
    assert tdc._get_user_role() is None


@pytest.mark.asyncio
async def test_tenant_session_sets_and_resets_gucs():
    tenant = ContextVar("tenant", default=None)
    role = ContextVar("role", default=None)
    tenant.set(42)
    role.set("manager")
    tdc._current_tenant_id, tdc._current_user_role = tenant, role

    session = AsyncMock()
    factory = MagicMock(return_value=session)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = context

    received = []
    async for value in tdc.tenant_session(factory):
        received.append(value)
    assert received == [session]
    assert session.execute.await_count == 4
    session.rollback.assert_awaited_once()
    statements = [call.args[0].text for call in session.execute.await_args_list]
    assert any("current_tenant_id" in statement for statement in statements)
    assert any("current_user_role" in statement for statement in statements)


@pytest.mark.asyncio
async def test_tenant_session_without_tenant_does_not_set_gucs_but_rolls_back():
    tenant = ContextVar("tenant_none", default=None)
    role = ContextVar("role_none", default=None)
    tdc._current_tenant_id, tdc._current_user_role = tenant, role
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=context)

    values = [value async for value in tdc.tenant_session(factory)]
    assert values == [session]
    session.execute.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_session_reset_errors_are_swallowed():
    tenant = ContextVar("tenant_error", default=8)
    role = ContextVar("role_error", default="admin")
    tdc._current_tenant_id, tdc._current_user_role = tenant, role
    session = AsyncMock()
    session.execute.side_effect = [None, None, RuntimeError("reset failed")]
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=context)

    values = [value async for value in tdc.tenant_session(factory)]
    assert values == [session]
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_assert_tenant_guc_set_returns_value_or_none():
    result = MagicMock()
    result.scalar_one_or_none.return_value = "42"
    session = AsyncMock()
    session.execute.return_value = result
    assert await tdc.assert_tenant_guc_set(session) == "42"
    result.scalar_one_or_none.return_value = ""
    assert await tdc.assert_tenant_guc_set(session) is None
