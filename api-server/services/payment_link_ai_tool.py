"""services/payment_link_ai_tool.py — Génération de liens de paiement depuis l'IA.

Utilisé par structured_agent.py pour créer automatiquement un lien de paiement
après confirmation d'une commande en conversation WhatsApp/Instagram/TikTok.

Le lien est créé via le modèle PaymentLink et l'invoice_service.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def generate_payment_link_for_ai(
    db,
    store,
    customer,
    amount: float,
    description: str,
    order_id: int | None = None,
    channel: str = "whatsapp",
    channel_client=None,
) -> dict[str, Any]:
    """Génère un lien de paiement pour l'IA conversationnelle.

    Args:
        db: Session SQLAlchemy async.
        store: Instance Store (ORM).
        customer: Instance Customer (ORM).
        amount: Montant en devise locale (ex: 45.000 pour TND).
        description: Description de la commande.
        order_id: ID de la commande associée (optionnel).
        channel: Canal d'origine ("whatsapp", "instagram", "tiktok", "facebook").
        channel_client: Client de canal pour envoi direct (optionnel — peut être None).

    Returns:
        dict avec les clés:
            success (bool): True si le lien a été créé avec succès.
            url (str | None): URL du lien de paiement.
            invoice_number (str | None): Référence facture.
            error (str | None): Message d'erreur si success=False.
    """
    if not store.payment_config or not store.onboarding_completed:
        return {
            "success": False,
            "url": None,
            "invoice_number": None,
            "error": "Store payment not configured",
        }

    try:
        from sqlalchemy import select

        from models.database import PaymentLink

        # Générer un numéro de facture unique
        invoice_prefix = f"INV-{store.id}"
        invoice_number = f"{invoice_prefix}-{uuid.uuid4().hex[:8].upper()}"

        # Construire l'URL du lien de paiement via storefront
        # L'URL réelle dépend du provider configuré (Paymee, Stripe, Flouci, etc.)
        server_domain = ""
        try:
            from config import settings
            server_domain = settings.SERVER_DOMAIN.rstrip("/")
        except Exception:
            server_domain = "http://localhost:8000"

        # Créer le PaymentLink en base
        token = uuid.uuid4().hex
        payment_link = PaymentLink(
            store_id=store.id,
            token=token,
            amount=amount,
            description=description,
            customer_id=customer.id if customer else None,
            order_id=order_id,
            invoice_number=invoice_number,
            channel=channel,
            status="pending",
        )
        db.add(payment_link)
        await db.flush()

        payment_url = f"{server_domain}/api/v1/storefront/pay/{token}"

        logger.info(
            "payment_link_ai_tool: created link store=%s amount=%s invoice=%s",
            store.id, amount, invoice_number,
        )

        return {
            "success": True,
            "url": payment_url,
            "invoice_number": invoice_number,
            "payment_link_id": payment_link.id,
            "error": None,
        }

    except Exception as exc:
        logger.warning("payment_link_ai_tool: creation failed — %s", exc)
        return {
            "success": False,
            "url": None,
            "invoice_number": None,
            "error": str(exc),
        }
