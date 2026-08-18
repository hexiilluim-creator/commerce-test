from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.expenses import ExpenseIn, ExpenseUpdate, create_expense, get_expense, get_summary, list_expenses, update_expense


def test_expense_schemas_validate_positive_amount():
    item = ExpenseIn(description="Stock", amount=10, expense_date=date(2026, 8, 1))
    assert item.currency == "TND"
    with pytest.raises(ValidationError):
        ExpenseIn(description="Bad", amount=0, expense_date=date.today())
    assert ExpenseUpdate(category="marketing").category.value == "marketing"


@pytest.mark.asyncio
async def test_create_and_get_expense_are_tenant_scoped():
    db = AsyncMock()
    db.refresh = AsyncMock()
    created = SimpleNamespace(id=7, store_id=4, description="Stock", amount=10)
    db.add.side_effect = lambda obj: setattr(obj, "id", 7)
    with patch("api.v1.expenses._sid", return_value=4):
        result = await create_expense(ExpenseIn(description="Stock", amount=10, expense_date=date.today()), db)
    assert result.store_id == 4 and result.description == "Stock"
    db.commit.assert_awaited_once()

    db.get.return_value = created
    with patch("api.v1.expenses._sid", return_value=4):
        assert await get_expense(7, db) is created
    db.get.return_value = None
    with patch("api.v1.expenses._sid", return_value=4):
        with pytest.raises(HTTPException) as exc:
            await get_expense(7, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_and_summary_expenses():
    db = AsyncMock()
    listed = MagicMock()
    listed.scalars.return_value.all.return_value = [SimpleNamespace(description="x")]
    db.execute.return_value = listed
    with patch("api.v1.expenses._sid", return_value=4):
        rows = await list_expenses(days=30, category="not-a-real-category", db=db)
    assert len(rows) == 1

    grouped = MagicMock()
    grouped.fetchall.return_value = [SimpleNamespace(category=SimpleNamespace(value="supplier"), total=100, count=2)]
    db.execute.return_value = grouped
    db.scalar.return_value = 50
    with patch("api.v1.expenses._sid", return_value=4):
        summary = await get_summary(days=30, db=db)
    assert summary["total"] == 100.0
    assert summary["categories"][0]["category"] == "supplier"
    assert summary["change_pct"] == 100.0


@pytest.mark.asyncio
async def test_update_expense_changes_only_provided_fields():
    db = AsyncMock()
    exp = SimpleNamespace(id=1, store_id=4, description="old", amount=5)
    db.get.return_value = exp
    with patch("api.v1.expenses._sid", return_value=4):
        result = await update_expense(1, ExpenseUpdate(description="new"), db)
    assert result.description == "new" and result.amount == 5
    db.commit.assert_awaited_once()
