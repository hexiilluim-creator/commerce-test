"""tests/test_loyalty_service.py — services/loyalty_service.py (Plan C1).

P1.2 : services/loyalty_service.py importait models.loyalty, un module qui
n'existait pas (découvert lors d'un audit de déploiement, juillet 2026).
Reconstruit dans models/loyalty.py à partir de l'usage réel du service.
Ce test valide que le module s'importe et fonctionne réellement (pas
seulement que l'import réussit).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.database import Base
from services.loyalty_service import earn_points, redeem_points


@pytest_asyncio.fixture
async def loyalty_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_earn_points_creates_account_and_credits_balance(loyalty_session):
    result = await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=50.0,
        source="order:123", idempotency_key="order:123:earn",
    )
    assert result.new_balance == 50
    assert result.account_id is not None


@pytest.mark.asyncio
async def test_earn_points_idempotent_on_repeated_key(loyalty_session):
    r1 = await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=50.0,
        source="order:123", idempotency_key="order:123:earn",
    )
    r2 = await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=50.0,
        source="order:123", idempotency_key="order:123:earn",
    )
    assert r2.ledger_id == r1.ledger_id
    assert r2.new_balance == r1.new_balance  # pas de double crédit


@pytest.mark.asyncio
async def test_redeem_points_debits_balance(loyalty_session):
    await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=50.0,
        source="order:123", idempotency_key="order:123:earn",
    )
    new_balance = await redeem_points(
        loyalty_session, store_id=1, customer_id=1, points=20,
        reason="reward:coupon", idempotency_key="redeem:1",
    )
    assert new_balance == 30


@pytest.mark.asyncio
async def test_redeem_points_rejects_insufficient_balance(loyalty_session):
    await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=10.0,
        source="order:123", idempotency_key="order:123:earn",
    )
    with pytest.raises(ValueError, match="Solde insuffisant"):
        await redeem_points(
            loyalty_session, store_id=1, customer_id=1, points=10_000,
            reason="reward:overdraft", idempotency_key="redeem:2",
        )


@pytest.mark.asyncio
async def test_accounts_are_isolated_per_store(loyalty_session):
    await earn_points(
        loyalty_session, store_id=1, customer_id=1, amount_eur=50.0,
        source="order:1", idempotency_key="s1:earn",
    )
    r2 = await earn_points(
        loyalty_session, store_id=2, customer_id=1, amount_eur=5.0,
        source="order:2", idempotency_key="s2:earn",
    )
    assert r2.new_balance == 5  # store 2 n'hérite pas du solde du store 1
