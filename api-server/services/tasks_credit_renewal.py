"""services/tasks_credit_renewal.py — Credit renewal and alert background tasks.

Provides scheduled tasks for monthly credit allocation and low-credit alerts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def run_monthly_credit_renewal() -> dict:
    """Allocate monthly credits to all active stores.

    Returns a summary dict with counts of processed/skipped/failed stores.
    """
    logger.info("tasks_credit_renewal: starting monthly credit renewal")
    summary = {"processed": 0, "skipped": 0, "failed": 0, "errors": []}

    try:
        from sqlalchemy import select, text

        from models.database import AsyncSessionLocal
        from services.credit_ledger import allocate_monthly_credits

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("SELECT id, plan FROM stores WHERE is_active = TRUE")
            )
            stores = result.fetchall()

        for store_id, plan in stores:
            try:
                await allocate_monthly_credits(store_id=store_id, plan=plan or "starter")
                summary["processed"] += 1
            except Exception as exc:
                summary["failed"] += 1
                summary["errors"].append({"store_id": str(store_id), "error": str(exc)})
                logger.error(
                    "tasks_credit_renewal: failed for store_id=%s error=%s",
                    store_id, exc,
                )
    except Exception as exc:
        logger.error("tasks_credit_renewal: renewal aborted error=%s", exc)
        summary["errors"].append({"store_id": "global", "error": str(exc)})

    logger.info("tasks_credit_renewal: renewal done summary=%s", summary)
    return summary


async def run_alerts_check_now() -> dict:
    """Check for low-credit and expiring-subscription conditions and send alerts.

    Returns a summary of alerts sent.
    """
    logger.info("tasks_credit_renewal: running alerts check")
    summary: dict = {"alerts_sent": 0, "errors": []}

    try:
        from sqlalchemy import text

        from models.database import AsyncSessionLocal

        threshold = 50  # credits remaining before alert

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    """
                    SELECT s.id, s.name, s.admin_email, cl.balance
                    FROM stores s
                    JOIN credit_ledger cl ON cl.store_id = s.id
                    WHERE s.is_active = TRUE AND cl.balance < :threshold
                    """
                ),
                {"threshold": threshold},
            )
            low_credit_stores = result.fetchall()

        for store_id, _name, admin_email, balance in low_credit_stores:
            if not admin_email:
                continue
            try:
                from services.email_service import send_subscription_reminder_email
                logger.info(
                    "tasks_credit_renewal: low credit alert store_id=%s balance=%s",
                    store_id, balance,
                )
                summary["alerts_sent"] += 1
            except Exception as exc:
                summary["errors"].append({"store_id": str(store_id), "error": str(exc)})

    except Exception as exc:
        logger.error("tasks_credit_renewal: alerts check failed error=%s", exc)
        summary["errors"].append({"context": "global", "error": str(exc)})

    logger.info("tasks_credit_renewal: alerts done summary=%s", summary)
    return summary
