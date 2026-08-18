"""Tests unitaires déterministes des garde-fous super-admin.

Ce lot couvre uniquement des comportements réels et observables : RBAC,
calcul calendaire, résolution du créateur et validation des schémas.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1 import super_admin as mod


@pytest.mark.parametrize(
    ("source", "months", "expected"),
    [
        (datetime(2024, 1, 31, 9, 30), 1, datetime(2024, 2, 29, 9, 30)),
        (datetime(2024, 12, 31), 2, datetime(2025, 2, 28)),
        (datetime(2025, 3, 30), -1, datetime(2025, 2, 28)),
        (datetime(2025, 6, 15), 0, datetime(2025, 6, 15)),
    ],
)
def test_add_calendar_months_clamps_days_and_crosses_years(source, months, expected):
    assert mod._add_calendar_months(source, months) == expected


@pytest.mark.asyncio
async def test_check_super_admin_accepts_context_role(monkeypatch):
    from middleware import tenant
    token = tenant.current_user_role.set("super_admin")
    try:
        assert await mod.check_super_admin(SimpleNamespace(state=SimpleNamespace())) is True
    finally:
        tenant.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_check_super_admin_rejects_missing_and_non_admin_roles(monkeypatch):
    class MissingContext:
        def get(self):
            raise LookupError("no context")

    monkeypatch.setattr("middleware.tenant.current_user_role", MissingContext())
    with pytest.raises(HTTPException) as missing:
        await mod.check_super_admin(SimpleNamespace(state=SimpleNamespace()))
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as forbidden:
        await mod.check_super_admin(SimpleNamespace(state=SimpleNamespace(role="admin")))
    assert forbidden.value.status_code == 403


def test_resolve_creator_prefers_request_state_email():
    request = SimpleNamespace(state=SimpleNamespace(user_email="state@example.test"))
    assert mod._resolve_creator(request) == "admin:state@example.test"


def test_resolve_creator_falls_back_when_context_email_is_unavailable():
    request = SimpleNamespace(state=SimpleNamespace())
    assert mod._resolve_creator(request) == "admin:superadmin"


def test_subscription_request_accepts_optional_fields_and_rejects_missing_required():
    payload = mod.CreateSubscriptionRequest(
        plan_code="business",
        duration_months=12,
        notes="annual contract",
        starts_at=datetime(2026, 1, 1),
    )
    assert payload.plan_code == "business"
    assert payload.duration_months == 12
    with pytest.raises(ValidationError):
        mod.CreateSubscriptionRequest(plan_code="business")


def test_update_subscription_request_enforces_days_bounds():
    assert mod.UpdateSubscriptionRequest(plan_code="starter").days == 30
    assert mod.UpdateSubscriptionRequest(plan_code="starter", days=3650).days == 3650
    with pytest.raises(ValidationError):
        mod.UpdateSubscriptionRequest(plan_code="starter", days=0)
    with pytest.raises(ValidationError):
        mod.UpdateSubscriptionRequest(plan_code="starter", days=3651)


def test_response_models_preserve_enterprise_contract_fields():
    store = mod.StoreDetail(id=1, name="Demo", admin_email=None, plan_code="starter", status="active", is_paid=False)
    page = mod.PaginatedStores(items=[store], total=1, page=1, page_size=50, total_pages=1)
    assert page.items[0].name == "Demo"
    assert page.total_pages == 1

    pricing = mod.PlanPricingResponse(plan_code="starter", plan_label="Starter", pricing=[{"months": 3, "price": 99}])
    assert pricing.pricing[0]["months"] == 3


@pytest.mark.asyncio
async def test_global_stats_aggregates_active_expiring_and_expired(monkeypatch):
    now = datetime.now(mod.UTC)
    class Scalar:
        def __init__(self, value): self.value = value
        def scalar(self): return self.value
    class Rows:
        def __init__(self, rows): self.rows = rows
        def all(self): return self.rows
    db = SimpleNamespace(execute=pytest.helpers if False else None)
    results = iter([Scalar(3), Scalar(12), Rows([(120.0, 12, None), (60.0, 6, now.replace(day=now.day) + mod.timedelta(days=1)), (99.0, 3, now.replace(year=now.year-1))]), Scalar(1), Scalar(2)])
    db.execute = AsyncMock(side_effect=lambda _stmt: next(results))
    out = await mod.get_global_stats.__wrapped__(SimpleNamespace(), db=db)
    assert out.total_stores == 3
    assert out.total_orders == 12
    assert out.active_subscriptions == 2
    assert out.total_revenue_monthly == 20.0
    assert out.expiring_soon == 1 and out.expired_count == 2


@pytest.mark.asyncio
async def test_list_all_stores_paginates_and_maps_subscription_overview(monkeypatch):
    store = SimpleNamespace(id=7, name="Garage", created_at=datetime(2026, 1, 2))
    count = SimpleNamespace(scalar=lambda: 1)
    rows = SimpleNamespace(all=lambda: [(store, "admin@example.test")])
    db = SimpleNamespace(execute=AsyncMock(side_effect=[count, rows]))
    monkeypatch.setattr(mod, "get_subscription_overview", AsyncMock(return_value={"plan_code": "starter", "status": "active", "is_paid": True, "expires_at": None}))
    out = await mod.list_all_stores.__wrapped__(SimpleNamespace(), db=db, page=1, page_size=50, search="Garage")
    assert out.total == 1 and out.items[0].admin_email == "admin@example.test"
    assert out.items[0].plan_code == "starter"
    assert out.items[0].features == sorted(list(mod.PLAN_CATALOG["starter"].features))


@pytest.mark.asyncio
async def test_list_all_stores_rolls_back_on_query_failure():
    rollback = AsyncMock()
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down")), rollback=rollback)
    with pytest.raises(HTTPException) as exc:
        await mod.list_all_stores.__wrapped__(SimpleNamespace(), db=db, page=1, page_size=10, search=None)
    assert exc.value.status_code == 500
    rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_suspend_and_reactivate_store_update_store_and_commit():
    store = SimpleNamespace(id=7, billing_status="active", suspended_at=None, suspended_reason=None)
    db = SimpleNamespace(get=AsyncMock(return_value=store), execute=AsyncMock(), commit=AsyncMock())
    suspended = await mod.suspend_store.__wrapped__(SimpleNamespace(), 7, "policy", db=db)
    assert suspended == {"status": "suspended", "store_id": 7}
    assert store.billing_status == "suspended" and store.suspended_reason == "policy"
    reactivated = await mod.reactivate_store.__wrapped__(SimpleNamespace(), 7, db=db)
    assert reactivated == {"status": "reactivated", "store_id": 7}
    assert store.billing_status == "active" and store.suspended_at is None
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_suspend_and_reactivate_missing_store_return_404():
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(), commit=AsyncMock())
    with pytest.raises(HTTPException) as suspended:
        await mod.suspend_store.__wrapped__(SimpleNamespace(), 99, "x", db=db)
    with pytest.raises(HTTPException) as reactivated:
        await mod.reactivate_store.__wrapped__(SimpleNamespace(), 99, db=db)
    assert suspended.value.status_code == 404 and reactivated.value.status_code == 404


@pytest.mark.asyncio
async def test_plans_pricing_exposes_catalog():
    out = await mod.get_plans_pricing.__wrapped__(SimpleNamespace())
    assert len(out) == len(mod.PLAN_CATALOG)
    assert {item.plan_code for item in out} == set(mod.PLAN_CATALOG)


@pytest.mark.asyncio
async def test_get_tenant_subscriptions_maps_rows_and_days_remaining():
    now = datetime.now(mod.UTC)
    sub = SimpleNamespace(id=1, tenant_id=7, plan_code="business", duration_months=12, price_paid_dt=120, starts_at=now, expires_at=now + mod.timedelta(days=5), status="active", reminder_7d_sent_at=None, reminder_1d_sent_at=None, blocked_at=None, created_by="admin", created_at=now)
    result = SimpleNamespace(all=lambda: [(sub, "Garage", "admin@example.test")])
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    out = await mod.get_tenant_subscriptions.__wrapped__(SimpleNamespace(), 7, db=db)
    assert out[0].store_name == "Garage" and out[0].days_remaining >= 4
    assert out[0].price_paid_dt == 120.0


@pytest.mark.asyncio
async def test_create_and_update_tenant_subscription_success(monkeypatch):
    now = datetime.now(mod.UTC)
    store = SimpleNamespace(id=7)
    sub = SimpleNamespace(id=11, plan_code="business")
    db = SimpleNamespace(get=AsyncMock(side_effect=[store, sub]), execute=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(mod, "upsert_subscription", AsyncMock(return_value=sub))
    monkeypatch.setattr(mod, "assert_plan_activation_allowed", lambda plan: None)
    request = SimpleNamespace(state=SimpleNamespace(user_email="admin@example.test"))
    created = await mod.create_tenant_subscription.__wrapped__(request, 7, mod.CreateSubscriptionRequest(plan_code="business", duration_months=3), db=db)
    assert created["status"] == "created" and created["subscription_id"] == 11
    active = {"id": 11}
    monkeypatch.setattr(mod, "_get_active_tenant_sub", AsyncMock(return_value=active))
    sub.expires_at = now
    updated = await mod.update_tenant_subscription.__wrapped__(request, 7, mod.UpdateSubscriptionRequest(plan_code="premium", days=30), db=db)
    assert updated == {"status": "updated", "subscription_id": 11}
    assert sub.plan_code == "premium" and db.commit.await_count == 2


@pytest.mark.asyncio
async def test_create_subscription_rejects_invalid_plan_and_missing_store(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(), commit=AsyncMock())
    request = SimpleNamespace(state=SimpleNamespace(user_email="admin@example.test"))
    with pytest.raises(HTTPException) as invalid:
        await mod.create_tenant_subscription.__wrapped__(request, 7, mod.CreateSubscriptionRequest(plan_code="starter", duration_months=2), db=db)
    assert invalid.value.status_code == 400
    # starter is valid; force the business rule branch instead
    monkeypatch.setattr(mod, "assert_plan_activation_allowed", lambda plan: (_ for _ in ()).throw(ValueError("blocked")))
    with pytest.raises(HTTPException) as blocked:
        await mod.create_tenant_subscription.__wrapped__(request, 7, mod.CreateSubscriptionRequest(plan_code="starter", duration_months=1), db=db)
    assert blocked.value.status_code == 409


@pytest.mark.asyncio
async def test_list_all_subscriptions_filters_and_maps_rows():
    now = datetime.now(mod.UTC)
    sub = SimpleNamespace(id=1, tenant_id=2, plan_code="starter", duration_months=1, price_paid_dt=None, starts_at=now, expires_at=now + mod.timedelta(days=2), status="active", reminder_7d_sent_at=None, reminder_1d_sent_at=None, blocked_at=None, created_by=None, created_at=now)
    result = SimpleNamespace(all=lambda: [(sub, "Store", "admin@example.test")])
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    out = await mod.list_all_subscriptions.__wrapped__(SimpleNamespace(), db=db, status="active", expiring_days=7)
    assert len(out) == 1 and out[0].tenant_id == 2 and out[0].days_remaining >= 1
    with pytest.raises(HTTPException) as bad:
        await mod.list_all_subscriptions.__wrapped__(SimpleNamespace(), db=db, status="bogus", expiring_days=None)
    assert bad.value.status_code == 400


@pytest.mark.asyncio
async def test_check_expired_subscriptions_blocks_tenants_and_empty_is_noop(monkeypatch):
    class Rows:
        def __init__(self, values): self.values = values
        def fetchall(self): return [(v,) for v in self.values]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[Rows([2, 3]), MagicMock(), MagicMock()]), commit=AsyncMock())
    monkeypatch.setattr("middleware.tenant.invalidate_tenant_state_cache", lambda tid: None)
    out = await mod.check_expired_subscriptions.__wrapped__(SimpleNamespace(), db=db)
    assert out == {"blocked": 2, "tenant_ids": [2, 3]}
    db_empty = SimpleNamespace(execute=AsyncMock(return_value=Rows([])), commit=AsyncMock())
    assert await mod.check_expired_subscriptions.__wrapped__(SimpleNamespace(), db=db_empty) == {"blocked": 0, "tenant_ids": []}


@pytest.mark.asyncio
async def test_send_subscription_reminders_marks_j7_and_j1(monkeypatch):
    now = datetime.now(mod.UTC)
    rows7 = [{"id": 1, "expires_at": now + mod.timedelta(days=5), "plan_code": "starter", "store_name": "A", "admin_email": "a@example.test"}]
    rows1 = [{"id": 2, "expires_at": now + mod.timedelta(hours=12), "plan_code": "business", "store_name": "B", "admin_email": "b@example.test"}]
    class Mappings:
        def __init__(self, rows): self.rows = rows
        def all(self): return self.rows
    r7 = SimpleNamespace(mappings=lambda: Mappings(rows7)); r1 = SimpleNamespace(mappings=lambda: Mappings(rows1))
    obj7 = SimpleNamespace(reminder_7d_sent_at=None); obj1 = SimpleNamespace(reminder_1d_sent_at=None)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[r7, r1]), get=AsyncMock(side_effect=[obj7, obj1]), add=MagicMock(), commit=AsyncMock())
    send = AsyncMock()
    monkeypatch.setattr("services.email_service.send_subscription_reminder_email", send)
    out = await mod.send_subscription_reminders.__wrapped__(SimpleNamespace(), db=db)
    assert out == {"reminders_7d_sent": 1, "reminders_1d_sent": 1}
    assert obj7.reminder_7d_sent_at is not None and obj1.reminder_1d_sent_at is not None
    assert send.await_count == 2
