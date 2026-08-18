"""tests/test_analytics_sentiment.py — api/v1/analytics.py::get_sentiment.

P1.12-FIX (audit externe, juillet 2026) : cet endpoint remplaçait
silencieusement l'absence de sentiment réel par une distribution inventée
(72 % / 18 % / 7 % / 3 %) — un marchand voyait des pourcentages qui ne
mesuraient rien, sans avertissement clair côté frontend. Corrigé pour ne
plus jamais fabriquer de chiffres. Ce test verrouille le comportement :
zéro conversation analysée -> distribution à zéro + has_real_data=False.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.v1.analytics import get_sentiment
from middleware.tenant import current_tenant_id
from models.database import Base, ConversationLog, Customer, Store


@pytest_asyncio.fixture
async def analytics_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        store = Store(name="Test Store", slug="test-store")
        session.add(store)
        await session.flush()
        customer = Customer(store_id=store.id, whatsapp_phone="+21600000000")
        session.add(customer)
        await session.flush()
        yield session, store.id, customer.id
    await engine.dispose()


@pytest.mark.asyncio
async def test_sentiment_no_data_returns_zeros_not_fabricated_numbers(analytics_session):
    """Aucune conversation -> pas de distribution inventée."""
    session, store_id, _ = analytics_session
    token = current_tenant_id.set(store_id)
    try:
        result = await get_sentiment(days=30, db=session)
    finally:
        current_tenant_id.reset(token)

    assert result["has_real_data"] is False
    assert result["total_analyzed"] == 0
    for entry in result["distribution"].values():
        assert entry["count"] == 0
        assert entry["pct"] == 0


@pytest.mark.asyncio
async def test_sentiment_conversations_without_payload_still_no_fabrication(analytics_session):
    """Des conversations existent mais aucune n'a de sentiment analysé ->
    toujours pas de distribution inventée (c'est exactement le bug corrigé :
    l'ancien code fabriquait 72/18/7/3 dans ce cas précis)."""
    session, store_id, customer_id = analytics_session
    for _ in range(10):
        session.add(ConversationLog(
            store_id=store_id, customer_id=customer_id,
            to_state="browsing", payload=None,
        ))
    await session.commit()

    token = current_tenant_id.set(store_id)
    try:
        result = await get_sentiment(days=30, db=session)
    finally:
        current_tenant_id.reset(token)

    assert result["total_analyzed"] == 10
    assert result["has_real_data"] is False
    for entry in result["distribution"].values():
        assert entry["count"] == 0


@pytest.mark.asyncio
async def test_sentiment_with_real_payload_reports_actual_counts(analytics_session):
    """Quand un vrai sentiment a été loggé, il doit être compté correctement."""
    session, store_id, customer_id = analytics_session
    sentiments = ["positive", "positive", "negative", "urgent"]
    for s in sentiments:
        session.add(ConversationLog(
            store_id=store_id, customer_id=customer_id,
            to_state="browsing", payload={"sentiment": s},
        ))
    await session.commit()

    token = current_tenant_id.set(store_id)
    try:
        result = await get_sentiment(days=30, db=session)
    finally:
        current_tenant_id.reset(token)

    assert result["has_real_data"] is True
    assert result["distribution"]["positive"]["count"] == 2
    assert result["distribution"]["negative"]["count"] == 1
    assert result["distribution"]["urgent"]["count"] == 1
    assert result["distribution"]["neutral"]["count"] == 0
