"""
services/loyalty_service.py — Plan C1 Loyalty: Points, History, Earn, Spend, Balance.

This is the Plan C complement referenced from Plan E3 (Loyalty IA) — the
client-side endpoints used to actually credit/debit the wallet that E3
segments analyse. Lives under `services/` so it can be reused by orders,
campaigns, and chat-agent flows alike.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.loyalty import (  # type: ignore[import-not-found]
    LoyaltyAccount,
    LoyaltyLedgerEntry,
    LoyaltyProgram,
    LoyaltyRule,
)


@dataclass
class EarnResult:
    account_id: int
    new_balance: int
    ledger_id: int
    rule_id: int | None


async def earn_points(
    session: AsyncSession,
    *,
    store_id: int,
    customer_id: int,
    amount_eur: float,
    source: str,
    idempotency_key: str,
    rule_id: int | None = None,
) -> EarnResult:
    """Idempotent credit. Repeated calls with the same key return the same ledger id."""
    # Idempotency: if ledger already recorded with this key, fetch it.
    existing = await session.execute(
        select(LoyaltyLedgerEntry).where(
            LoyaltyLedgerEntry.idempotency_key == idempotency_key
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        acc_res = await session.execute(
            select(LoyaltyAccount).where(LoyaltyAccount.id == row.account_id)
        )
        acc = acc_res.scalar_one()
        return EarnResult(account_id=acc.id, new_balance=acc.balance, ledger_id=row.id,
                          rule_id=row.rule_id)

    # Find or create the account.
    acc_res = await session.execute(
        select(LoyaltyAccount).where(
            LoyaltyAccount.store_id == store_id,
            LoyaltyAccount.customer_id == customer_id,
        )
    )
    acc = acc_res.scalar_one_or_none()
    if acc is None:
        acc = LoyaltyAccount(store_id=store_id, customer_id=customer_id, balance=0)
        session.add(acc)
        await session.flush()

    # Pick a default rule if none supplied: 1 pt per 1 €.
    if rule_id is None:
        rule_res = await session.execute(
            select(LoyaltyRule).where(
                LoyaltyRule.store_id == store_id, LoyaltyRule.is_active.is_(True)
            ).order_by(LoyaltyRule.id.asc()).limit(1)
        )
        rule = rule_res.scalar_one_or_none()
        if rule is None:
            points = int(round(amount_eur))  # sensible default
        else:
            points = int(round(amount_eur * rule.points_per_eur))
    else:
        points = int(round(amount_eur))

    acc.balance += points
    ledger = LoyaltyLedgerEntry(
        account_id=acc.id,
        kind="earn",
        points=points,
        source=source,
        idempotency_key=idempotency_key,
        amount_eur=amount_eur,
        rule_id=rule_id,
        created_at=datetime.now(UTC),
    )
    session.add(ledger)
    await session.flush()
    return EarnResult(account_id=acc.id, new_balance=acc.balance, ledger_id=ledger.id,
                      rule_id=ledger.rule_id)


async def redeem_points(
    session: AsyncSession,
    *,
    store_id: int,
    customer_id: int,
    points: int,
    reason: str,
    idempotency_key: str,
) -> int:
    """Atomic debit; raises if insufficient balance."""
    if points <= 0:
        raise ValueError("points must be > 0")
    acc_res = await session.execute(
        select(LoyaltyAccount).where(
            LoyaltyAccount.store_id == store_id,
            LoyaltyAccount.customer_id == customer_id,
        ).with_for_update()
    )
    acc = acc_res.scalar_one_or_none()
    if acc is None or acc.balance < points:
        raise ValueError("Solde insuffisant")

    # Idempotency: coins can be debited via different orders with same key.
    dup = await session.execute(
        select(LoyaltyLedgerEntry).where(LoyaltyLedgerEntry.idempotency_key == idempotency_key)
    )
    if dup.scalar_one_or_none() is not None:
        return acc.balance

    acc.balance -= points
    session.add(LoyaltyLedgerEntry(
        account_id=acc.id,
        kind="spend",
        points=-points,
        source=reason,
        idempotency_key=idempotency_key,
        created_at=datetime.now(UTC),
    ))
    await session.flush()
    return acc.balance
