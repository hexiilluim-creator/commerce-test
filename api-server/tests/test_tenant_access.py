from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from services import tenant_access


class _DummyField:
    def __eq__(self, other: object) -> tuple[str, object]:
        return ("eq", other)


class _DummyStoreModel:
    id = _DummyField()


class _DummyQuery:
    def where(self, *conditions: object) -> _DummyQuery:
        self.conditions = conditions
        return self


class _FakeResult:
    def __init__(self, store) -> None:
        self._store = store

    def scalar_one_or_none(self):
        return self._store


class _FakeDB:
    def __init__(self, store=None, error: Exception | None = None) -> None:
        self.store = store
        self.error = error
        self.executed_query = None

    async def execute(self, query):
        if self.error is not None:
            raise self.error
        self.executed_query = query
        return _FakeResult(self.store)


@pytest.fixture(autouse=True)
def patch_store_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("models.database")
    fake_module.Store = _DummyStoreModel
    monkeypatch.setitem(sys.modules, "models.database", fake_module)
    monkeypatch.setattr(tenant_access, "select", lambda model: _DummyQuery())


@pytest.mark.asyncio
async def test_get_tenant_access_state_returns_store_snapshot() -> None:
    db = _FakeDB(
        store=SimpleNamespace(is_active=False, billing_status="past_due", suspended_reason="invoice")
    )

    state = await tenant_access.get_tenant_access_state(db, 77)

    assert state == tenant_access.TenantAccessState(
        is_tenant_active=False,
        billing_status="past_due",
        suspended_reason="invoice",
    )


@pytest.mark.asyncio
async def test_get_tenant_access_state_fails_closed_when_store_not_found() -> None:
    db = _FakeDB(store=None)

    state = await tenant_access.get_tenant_access_state(db, 88)

    assert state == tenant_access.TenantAccessState(
        is_tenant_active=False,
        billing_status="unknown",
        suspended_reason="tenant_not_found",
    )


@pytest.mark.asyncio
async def test_get_tenant_access_state_fails_closed_on_exception() -> None:
    db = _FakeDB(error=RuntimeError("db down"))

    state = await tenant_access.get_tenant_access_state(db, 99)

    assert state == tenant_access.TenantAccessState(
        is_tenant_active=False,
        billing_status="unavailable",
        suspended_reason="tenant_state_unavailable",
    )


@pytest.mark.asyncio
async def test_is_tenant_active_returns_boolean_flag() -> None:
    db = _FakeDB(store=SimpleNamespace(is_active=True, billing_status=None, suspended_reason=None))

    assert await tenant_access.is_tenant_active(db, 101) is True
