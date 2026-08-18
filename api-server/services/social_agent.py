"""
services/social_agent.py — Agent IA Omnicanal (BLOC 10)
=========================================================
Reçoit les messages entrants Instagram / Facebook / TikTok,
résout ou crée le Customer, puis délègue à ai_agent.py avec
le bon ChannelRouter pour répondre sur le bon canal.

Architecture :
  social_webhooks.py -> social_agent.handle_social_message()
                          -> _get_or_create_social_customer()
                          -> ai_agent.handle_text_message(wa_client=ChannelRouter)
                          -> ChannelRouter.send_text() -> instagram/facebook/tiktok API
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Customer, Store, get_db
from services import ai_agent
from utils.channel_router import ChannelRouter

logger = logging.getLogger(__name__)

SocialChannel = Literal["instagram", "facebook", "tiktok"]


# ─── Customer resolution ──────────────────────────────────────────────────────

async def _get_or_create_social_customer(
    db: AsyncSession,
    store: Store,
    sender_id: str,
    channel: SocialChannel,
) -> Customer:
    """
    Trouve ou crée un Customer pour un sender social (PSID/OpenID).
    Utilise (store_id, channel, social_sender_id) comme clé unique.
    WhatsApp_phone est renseigné avec une valeur synthétique non-nulle
    pour respecter la contrainte DB existante.
    """
    # Chercher le customer existant par canal + sender_id
    result = await db.execute(
        select(Customer)
        .where(
            Customer.store_id == store.id,
            Customer.channel == channel,
            Customer.social_sender_id == sender_id,
        )
        .with_for_update()
    )
    customer = result.scalar_one_or_none()

    if customer:
        return customer

    # Créer un nouveau customer social
    # whatsapp_phone : valeur synthétique unique pour respecter la contrainte DB
    # Format : {channel}_{sender_id[:20]}
    synthetic_phone = f"{channel}_{sender_id[:50]}"

    customer = Customer(
        store_id=store.id,
        whatsapp_phone=synthetic_phone,
        channel=channel,
        social_sender_id=sender_id,
        language=store.language or "fr",
        conversation_state={"fsm_state": "idle"},
    )
    db.add(customer)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(Customer)
            .where(
                Customer.store_id == store.id,
                Customer.channel == channel,
                Customer.social_sender_id == sender_id,
            )
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing
        raise
    logger.info(
        "New social customer created — store=%s channel=%s sender=%s customer_id=%s",
        store.id, channel, sender_id, customer.id,
    )
    return customer


# ─── Store resolution ─────────────────────────────────────────────────────────

async def _get_store(db: AsyncSession, store_id: int) -> Store | None:
    result = await db.execute(
        select(Store).where(Store.id == store_id, Store.is_active)
    )
    return result.scalar_one_or_none()


# ─── Main entry point ─────────────────────────────────────────────────────────

async def handle_social_message(
    store_id: int,
    channel: SocialChannel,
    sender_id: str,
    message_text: str | None,
    message_type: str = "text",
    attachments: list[dict] | None = None,
) -> dict:
    """
    Point d'entrée principal pour les messages entrants sociaux.
    Appelé depuis social_webhooks.py (BackgroundTask ou directement).

    Args:
        store_id     : ID du store résolu depuis recipient_id
        channel      : "instagram" | "facebook" | "tiktok"
        sender_id    : PSID ou Open ID de l'expéditeur
        message_text : Contenu texte du message (None si image/audio)
        message_type : "text" | "image" | "audio"
        attachments  : Liste des pièces jointes normalisées

    Returns:
        dict avec status, channel, reply (ou error)
    """
    if not store_id:
        logger.warning(
            "handle_social_message called with store_id=None for channel=%s sender=%s — dropped",
            channel, sender_id,
        )
        return {"status": "dropped", "reason": "store_id_not_resolved"}

    async for db in get_db():
        try:
            store = await _get_store(db, store_id)
            if not store:
                logger.error("Store %s not found or inactive", store_id)
                return {"status": "error", "reason": "store_not_found"}

            customer = await _get_or_create_social_customer(db, store, sender_id, channel)

            # Construire le ChannelRouter pour ce store + canal
            channel_router = ChannelRouter(store, channel=channel)

            if not channel_router.is_configured:
                logger.warning(
                    "Channel %s not configured for store %s — cannot reply",
                    channel, store_id,
                )
                return {"status": "dropped", "reason": "channel_not_configured"}

            # Traiter selon le type de message
            if message_type == "text" and message_text:
                # Priorité : structured_agent (RDV / auto_parts / ecommerce selon business_type)
                try:
                    from services.tasks import _dispatch_by_business_type
                    reply = await _dispatch_by_business_type(
                        db, store, customer, message_text, channel_router
                    )
                except Exception as _e:
                    logger.warning(f"dispatch failed for social, falling back: {_e}")
                    reply = await ai_agent.handle_text_message(
                    db=db,
                    store=store,
                    customer=customer,
                    text=message_text,
                    wa_client=channel_router,  # ChannelRouter implémente la même interface
                )
                return {"status": "ok", "channel": channel, "reply": reply}

            elif message_type == "image" and attachments:
                # Pour les images sociales : envoyer un message d'accusé de réception
                # L'analyse vision (analyze_whatsapp_image) est spécifique à WhatsApp pour l'instant
                # TODO BLOC 11 : étendre vision_analyzer pour URLs d'images publiques
                #
                # V28 P1-fix : la vision n'a pas tourné sur ce message, donc on ne
                # renvoie plus status="ok" (ça faisait croire aux métriques/logs
                # que le message était traité normalement). Kill switch explicite
                # + log WARNING pour que ce soit visible en observabilité tant
                # que BLOC 11 n'est pas livré.
                logger.warning(
                    "social image received without vision analysis — channel=%s store=%s sender=%s "
                    "(VISION_SOCIAL_ENABLED=%s)",
                    channel, store_id, sender_id, os.environ.get("VISION_SOCIAL_ENABLED", "0"),
                )
                ack_text = (
                    "Merci pour votre image ! 📸 Je l'ai bien reçue. "
                    "Pourriez-vous me décrire ce que vous recherchez en texte ?"
                )
                await channel_router.send_text(sender_id, ack_text)
                return {"status": "received_no_vision", "channel": channel, "reply": ack_text}

            else:
                # Type inconnu ou message vide
                fallback = "Bonjour ! Comment puis-je vous aider ? 😊"
                await channel_router.send_text(sender_id, fallback)
                return {"status": "ok", "channel": channel, "reply": fallback}

        except Exception as exc:
            logger.error(
                "handle_social_message error — channel=%s store=%s sender=%s: %s",
                channel, store_id, sender_id, exc,
            )
            return {"status": "error", "reason": str(exc)}


# ─── Async wrapper pour BackgroundTasks ──────────────────────────────────────

def handle_social_message_sync(
    store_id: int | None,
    channel: SocialChannel,
    sender_id: str | None,
    message_text: str | None,
    message_type: str = "text",
    attachments: list[dict] | None = None,
) -> None:
    """
    Wrapper synchrone pour usage dans FastAPI BackgroundTasks.
    Gère les cas None silencieusement (store_id non résolu).
    """
    import asyncio

    if not store_id or not sender_id:
        logger.debug(
            "social_agent: skipping — store_id=%s sender_id=%s channel=%s",
            store_id, sender_id, channel,
        )
        return

    try:
        asyncio.run(
            handle_social_message(
                store_id=store_id,
                channel=channel,
                sender_id=sender_id,
                message_text=message_text,
                message_type=message_type,
                attachments=attachments,
            )
        )
    except Exception as exc:
        logger.error("social_agent background task failed: %s", exc)


async def handle_social_event(*, platform: str, store_id: int, payload: dict, db: AsyncSession) -> dict:
    """Façade worker pour les webhooks sociaux entrants.

    Le worker reçoit le payload brut ; cette façade extrait le premier message
    normalisé puis délègue au point d’entrée social public. ``db`` est conservé
    dans la signature pour compatibilité avec les workers isolés.
    """
    entry = payload.get("entry", [{}])[0] if isinstance(payload, dict) else {}
    change = entry.get("messaging", [{}])[0] if isinstance(entry, dict) else {}
    sender = change.get("sender", {}).get("id") or payload.get("sender_id", "")
    message = change.get("message", {}) if isinstance(change, dict) else {}
    text = message.get("text") if isinstance(message, dict) else payload.get("message_text")
    channel = platform if platform in {"instagram", "facebook", "tiktok"} else "facebook"
    return await handle_social_message(
        store_id=store_id,
        channel=channel,
        sender_id=sender,
        message_text=text,
        message_type="text" if text else "unknown",
        attachments=None,
    )
