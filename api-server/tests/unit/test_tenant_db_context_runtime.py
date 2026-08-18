from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import tenant_db_context


@pytest.mark.asyncio
async def test_tenant_session_injects_and_resets_guc():
    session = AsyncMock()
    factory = lambda: _SessionContext(session)
    with patch("services.tenant_db_context._get_tenant_id", return_value=17), patch("services.tenant_db_context._get_user_role", return_value="admin"):
        async for yielded in tenant_db_context.tenant_session(factory):
            assert yielded is session
    assert session.execute.await_count >= 4
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_session_without_tenant_only_rolls_back():
    session = AsyncMock()
    factory = lambda: _SessionContext(session)
    with patch("services.tenant_db_context._get_tenant_id", return_value=None), patch("services.tenant_db_context._get_user_role", return_value=None):
        async for yielded in tenant_db_context.tenant_session(factory):
            assert yielded is session
    session.rollback.assert_awaited_once()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_assert_tenant_guc_set_returns_value_or_none():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "17"
    session.execute.return_value = result
    assert await tenant_db_context.assert_tenant_guc_set(session) == "17"
    result.scalar_one_or_none.return_value = ""
    assert await tenant_db_context.assert_tenant_guc_set(session) is None


class _SessionContext:
    def __init__(self, session):
        self.session = session
    async def __aenter__(self):
        return self.session
    async def __aexit__(self, exc_type, exc, tb):
        return False
