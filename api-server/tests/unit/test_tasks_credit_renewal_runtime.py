from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.tasks_credit_renewal import run_alerts_check_now, run_monthly_credit_renewal


class AsyncSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_monthly_credit_renewal_processed_failed_and_default_plan():
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [(1, "growth"), (2, None), (3, "business")]
    db.execute.return_value = result
    allocate = AsyncMock(side_effect=[None, RuntimeError("ledger down"), None])
    with patch("models.database.AsyncSessionLocal", return_value=AsyncSessionContext(db)), \
         patch("services.credit_ledger.allocate_monthly_credits", new=allocate):
        summary = await run_monthly_credit_renewal()
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["errors"][0]["store_id"] == "2"
    assert allocate.await_args_list[1].kwargs["plan"] == "starter"


@pytest.mark.asyncio
async def test_monthly_credit_renewal_global_db_failure():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db unavailable")
    with patch("models.database.AsyncSessionLocal", return_value=AsyncSessionContext(db)):
        summary = await run_monthly_credit_renewal()
    assert summary["processed"] == 0
    assert summary["errors"][0]["store_id"] == "global"


@pytest.mark.asyncio
async def test_alerts_check_counts_only_stores_with_email():
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [(1, "A", "a@example.com", 10), (2, "B", None, 5)]
    db.execute.return_value = result
    with patch("models.database.AsyncSessionLocal", return_value=AsyncSessionContext(db)):
        summary = await run_alerts_check_now()
    assert summary["alerts_sent"] == 1
    assert summary["errors"] == []


@pytest.mark.asyncio
async def test_alerts_global_failure_is_reported():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db unavailable")
    with patch("models.database.AsyncSessionLocal", return_value=AsyncSessionContext(db)):
        summary = await run_alerts_check_now()
    assert summary["alerts_sent"] == 0
    assert summary["errors"][0]["context"] == "global"
