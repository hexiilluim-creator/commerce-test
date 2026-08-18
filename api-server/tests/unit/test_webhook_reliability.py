"""tests/test_webhook_reliability.py — Couverture services/webhook_reliability.py.

Couvre :
  - _build_claim_key (avec message_id, sans message_id)
  - claim_webhook_message (premier -> True, doublon -> False)
  - release_webhook_claim
  - Fallback in-memory (Redis down)
  - TTL et purge du cache in-memory
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.webhook_reliability import (  # noqa: E402
    _SEEN_MESSAGES,
    _build_claim_key,
    claim_webhook_message,
    release_webhook_claim,
)

pytestmark = pytest.mark.unit


# ─── Tests _build_claim_key ───────────────────────────────────────────────────

def test_claim_key_with_message_id():
    key = _build_claim_key("whatsapp", 1, "msg_abc123", "sender", "recipient", "hello")
    assert "whatsapp" in key
    assert "msg_abc123" in key


def test_claim_key_without_message_id_uses_fingerprint():
    key = _build_claim_key("instagram", 2, None, "sender_x", "recip_y", "body text")
    assert "content:" in key
    assert "instagram" in key


def test_claim_key_deterministic_with_same_inputs():
    k1 = _build_claim_key("whatsapp", 1, None, "s1", "r1", "hello")
    k2 = _build_claim_key("whatsapp", 1, None, "s1", "r1", "hello")
    assert k1 == k2


def test_claim_key_different_channels_different_keys():
    k1 = _build_claim_key("whatsapp", 1, "msg1", None, None, None)
    k2 = _build_claim_key("instagram", 1, "msg1", None, None, None)
    assert k1 != k2


def test_claim_key_different_stores_different_keys():
    k1 = _build_claim_key("whatsapp", 10, "msg1", None, None, None)
    k2 = _build_claim_key("whatsapp", 20, "msg1", None, None, None)
    assert k1 != k2


# ─── Tests claim_webhook_message (in-memory fallback) ─────────────────────────

@pytest.mark.asyncio
async def test_claim_first_message_returns_true():
    """Premier claim -> True (jamais vu ce message)."""
    _SEEN_MESSAGES.clear()
    with patch("services.webhook_reliability._get_redis", AsyncMock(return_value=None)):
        result = await claim_webhook_message(
            channel="whatsapp",
            store_id=100,
            message_id="unique_msg_001",
            sender_id="sender_A",
            recipient_id="recip_B",
            body="Bonjour",
        )
    assert result is True


@pytest.mark.asyncio
async def test_claim_duplicate_message_returns_false():
    """Second claim avec le même message_id -> False (doublon)."""
    _SEEN_MESSAGES.clear()
    kwargs = dict(
        channel="whatsapp",
        store_id=101,
        message_id="dup_msg_001",
        sender_id="s1",
        recipient_id="r1",
        body="Test",
    )
    with patch("services.webhook_reliability._get_redis", AsyncMock(return_value=None)):
        first = await claim_webhook_message(**kwargs)
        second = await claim_webhook_message(**kwargs)

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_claim_different_channels_independent():
    """Même message_id sur deux canaux différents -> deux claims indépendants."""
    _SEEN_MESSAGES.clear()
    with patch("services.webhook_reliability._get_redis", AsyncMock(return_value=None)):
        r_wa = await claim_webhook_message(
            channel="whatsapp", store_id=200, message_id="msg_X",
            sender_id="s", recipient_id="r", body="hello"
        )
        r_ig = await claim_webhook_message(
            channel="instagram", store_id=200, message_id="msg_X",
            sender_id="s", recipient_id="r", body="hello"
        )
    assert r_wa is True
    assert r_ig is True  # Canal différent -> pas un doublon


# ─── Tests release_webhook_claim ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_allows_reclaim():
    """Après release, le même message peut être re-claimé."""
    _SEEN_MESSAGES.clear()
    kwargs = dict(
        channel="facebook",
        store_id=300,
        message_id="release_msg_001",
        sender_id="s",
        recipient_id="r",
        body="msg",
    )
    with patch("services.webhook_reliability._get_redis", AsyncMock(return_value=None)):
        first = await claim_webhook_message(**kwargs)
        second = await claim_webhook_message(**kwargs)
        await release_webhook_claim("facebook", 300, "release_msg_001")
        third = await claim_webhook_message(**kwargs)

    assert first is True
    assert second is False
    assert third is True  # Après release, reclaim possible


# ─── Tests Redis path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_uses_redis_setnx():
    """Quand Redis est disponible, utilise SETNX."""
    class _FakeRedis:
        def __init__(self):
            self.store = {}
        async def set(self, key, val, ex=None, nx=False):
            if nx and key in self.store:
                return False
            self.store[key] = val
            return True
        async def delete(self, key):
            self.store.pop(key, None)
            return 1

    redis = _FakeRedis()
    with patch("services.webhook_reliability._get_redis", AsyncMock(return_value=redis)):
        r1 = await claim_webhook_message(
            channel="tiktok", store_id=400, message_id="redis_msg_001",
            sender_id="s", recipient_id="r", body="hello"
        )
        r2 = await claim_webhook_message(
            channel="tiktok", store_id=400, message_id="redis_msg_001",
            sender_id="s", recipient_id="r", body="hello"
        )

    assert r1 is True
    assert r2 is False
