from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import redis_session_cleanup as rsc


class FakeRedis:
    def __init__(self):
        self.data = {
            "reset_token": [b"reset_token:missing", "reset_token:used", "reset_token:valid"],
            "pw": ["auth:pw_changed:abc", "auth:pw_changed:999"],
            "black": ["refresh:blacklist:old"],
        }
        self.ttls = {"reset_token:missing": 100, "reset_token:used": 100, "reset_token:valid": -1,
                     "auth:pw_changed:abc": 100, "auth:pw_changed:999": -1, "refresh:blacklist:old": -1}
        self.deleted = []
        self.expired = []

    async def scan(self, cursor=0, match=None, count=200):
        if cursor != 0:
            return 0, []
        if match == "reset_token:*": return 0, self.data["reset_token"]
        if match == "auth:pw_changed:*": return 0, self.data["pw"]
        if match == "refresh:blacklist:*": return 0, self.data["black"]
        return 0, []

    async def ttl(self, key): return self.ttls.get(key, -2)
    async def delete(self, key): self.deleted.append(key); return 1
    async def expire(self, key, seconds): self.expired.append((key, seconds)); return True

@pytest.mark.asyncio
async def test_scan_keys_decodes_bytes_and_supports_multiple_pages():
    redis = AsyncMock()
    redis.scan = AsyncMock(side_effect=[(2, [b"a"]), (0, ["b"])])
    values = [value async for value in rsc._scan_keys(redis, "x:*", 5)]
    assert values == ["a", "b"]
    assert redis.scan.await_count == 2

@pytest.mark.asyncio
async def test_cleanup_orphaned_sessions_deletes_orphans_and_restores_ttls():
    redis = FakeRedis()
    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    missing = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    used = SimpleNamespace(used=True, expires_at=datetime.now(UTC) + timedelta(hours=1), user_id=1)
    valid = SimpleNamespace(used=False, expires_at=datetime.now(UTC) + timedelta(hours=1), user_id=2)
    db.execute = AsyncMock(side_effect=[missing, MagicMock(scalar_one_or_none=MagicMock(return_value=used)), MagicMock(scalar_one_or_none=MagicMock(return_value=valid))])
    db.get = AsyncMock(return_value=SimpleNamespace(is_active=True))
    with patch.object(rsc, "get_redis", return_value=redis), patch.object(rsc, "AsyncSessionLocal", return_value=db):
        stats = await rsc.cleanup_orphaned_redis_sessions(batch_size=10)
    assert stats["reset_tokens_scanned"] == 3
    assert stats["reset_tokens_deleted"] == 2
    assert stats["ttls_restored"] >= 1
    assert "reset_token:missing" in redis.deleted
    assert "reset_token:used" in redis.deleted

@pytest.mark.asyncio
async def test_cleanup_handles_password_change_and_blacklist_rules():
    redis = FakeRedis()
    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.get = AsyncMock(side_effect=[None, SimpleNamespace(is_active=True)])
    with patch.object(rsc, "get_redis", return_value=redis), patch.object(rsc, "AsyncSessionLocal", return_value=db):
        stats = await rsc.cleanup_orphaned_redis_sessions()
    assert stats["password_change_keys_scanned"] == 2
    assert stats["password_change_deleted"] == 2
    assert stats["refresh_blacklist_deleted"] == 1
    assert "auth:pw_changed:abc" in redis.deleted
    assert "refresh:blacklist:old" in redis.deleted

@pytest.mark.asyncio
async def test_cleanup_counts_errors_and_continues():
    redis = FakeRedis()
    redis.ttl = AsyncMock(side_effect=RuntimeError("redis down"))
    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    with patch.object(rsc, "get_redis", return_value=redis), patch.object(rsc, "AsyncSessionLocal", return_value=db):
        stats = await rsc.cleanup_orphaned_redis_sessions()
    assert stats["errors"] == 6
    assert stats["reset_tokens_scanned"] == 3
    assert stats["password_change_keys_scanned"] == 2
    assert stats["refresh_blacklist_scanned"] == 1
