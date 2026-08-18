from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import session_cleanup as sc


@pytest.mark.asyncio
async def test_cleanup_pass_deletes_expired_and_used_tokens_and_commits():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    first = MagicMock(rowcount=3)
    second = MagicMock(rowcount=2)
    session.execute = AsyncMock(side_effect=[first, second])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    with patch.object(sc, "AsyncSessionLocal", return_value=session):
        result = await sc._run_cleanup_pass()
    assert result == {"password_reset_tokens": 5}
    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()

@pytest.mark.asyncio
async def test_cleanup_pass_rolls_back_on_database_error():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    with patch.object(sc, "AsyncSessionLocal", return_value=session):
        result = await sc._run_cleanup_pass()
    assert result == {"password_reset_tokens": 0}
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()

@pytest.mark.asyncio
async def test_cleanup_pass_handles_zero_rowcounts():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(side_effect=[MagicMock(rowcount=0), MagicMock(rowcount=None)])
    session.commit = AsyncMock()
    with patch.object(sc, "AsyncSessionLocal", return_value=session):
        result = await sc._run_cleanup_pass()
    assert result["password_reset_tokens"] == 0

@pytest.mark.asyncio
async def test_cleanup_job_cancellation_before_first_pass():
    async def cancel_sleep(seconds):
        raise asyncio.CancelledError
    import asyncio
    with patch.object(sc.asyncio, "sleep", side_effect=cancel_sleep), patch.object(sc, "_run_cleanup_pass", new=AsyncMock()) as cleanup:
        with pytest.raises(asyncio.CancelledError):
            await sc.start_cleanup_job()
    cleanup.assert_not_awaited()

@pytest.mark.asyncio
async def test_cleanup_job_runs_and_cancels_during_interval():
    import asyncio
    calls = 0
    async def sleep(seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        raise asyncio.CancelledError
    with patch.object(sc.asyncio, "sleep", side_effect=sleep), patch.object(sc, "_run_cleanup_pass", new=AsyncMock(return_value={"password_reset_tokens": 0})) as cleanup:
        with pytest.raises(asyncio.CancelledError):
            await sc.start_cleanup_job()
    cleanup.assert_awaited_once()
