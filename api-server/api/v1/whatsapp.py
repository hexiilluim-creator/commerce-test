"""api/v1/whatsapp.py — WhatsApp Cloud API webhook (V8 + Shadow Mode V9 + Active Rollout V9)

Fixes appliqués (V8 inchangé) :
  - P0-4: store_id résolu depuis phone_number_id via DB lookup (pas de hardcode)
  - P0-6: interactive button_reply et list_reply dispatchés vers la tâche Celery
  - Fallback gracieux si phone_number_id inconnu (log + 200, jamais 4xx vers Meta)

BLOC 7 — Shadow Mode V9 :
  - V8 inchangé : le résultat V8 est toujours retourné.
  - V9 tourne en parallèle via BackgroundTasks (non-bloquant).

BLOC 9 — Active Rollout V9 :
  - Utilise active_router pour décider du routage.
  - Fail-safe : retourne toujours le résultat V8 pour garantir zéro régression.

FIX v20.3 — Anti-double réponse WhatsApp :
  - Déduplication Redis (TTL 24h) sur message_id avant tout traitement.
  - Évite les double-traitements causés par les retransmissions Meta.

VERSION: v24
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from middleware.tenant import current_tenant_id
from models.database import StorePhoneMapping, get_db
from omnicall_v9.active_router import (
    get_active_route_decision,
    route_to_v9_if_enabled,
    run_active_v9,
)
from services import message_queue as _mq  # Phase 2: Redis Streams
from services import metrics as _metrics  # Phase 6: Prometheus
from services.tasks import process_whatsapp_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

# ─── Clé Redis pour la déduplication anti-double réponse ──────────────────────
_WA_DEDUP_PREFIX = "omnicall:wa:dedup:"
_WA_DEDUP_TTL_SECONDS = 86400  # 24 heures

# ─── Pool Redis async partagé (V24 ENTERPRISE FIX: remplace _get_redis_sync()) ─
# Un pool unique par process — pas de nouvelle connexion à chaque appel webhook.
_redis_pool: Any | None = None


async def _get_async_redis():
    """Retourne le client Redis async partagé (pool de connexions).

    V24 ENTERPRISE FIX: remplace _get_redis_sync() qui créait une nouvelle
    connexion synchrone à chaque webhook. Sous charge (1000+ webhooks/min),
    cela saturait le pool Redis et bloquait l'event loop FastAPI.

    Utilise un pool aioredis partagé par process — compatible multi-worker Uvicorn
    car chaque worker a son propre event loop et son propre pool.
    """
    global _redis_pool
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        if _redis_pool is None:
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_pool = aioredis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                max_connections=20,
            )
        await _redis_pool.ping()
        return _redis_pool
    except Exception as exc:
        logger.warning("whatsapp._get_async_redis failed: %s", exc)
        _redis_pool = None
        return None


def _build_canonical_payload(
    *,
    msg: dict,
    store_id: int,
    phone_number_id: str | None,
) -> dict:
    """Construit un payload canonique compatible webhook/Celery/OmniCall."""
    return {
        "message_id": msg.get("id"),
        "id": msg.get("id"),
        "from_phone": msg.get("from"),
        "from": msg.get("from"),
        "type": msg.get("type"),
        "message_type": msg.get("type"),
        "store_id": store_id,
        "phone_number_id": phone_number_id,
        "raw_message": dict(msg),
    }


async def _is_duplicate_wa_message(msg_id: str, store_id: int) -> bool:
    """Anti-double réponse WhatsApp — FIX v20.3 / V24 ENTERPRISE.

    Vérifie si ce message_id a déjà été traité via Redis SET NX.
    Meta peut envoyer le même webhook plusieurs fois (retry, réseau instable).

    V24 ENTERPRISE FIX: utilise le pool aioredis partagé (_get_async_redis)
    au lieu de créer une connexion Redis synchrone par appel (_get_redis_sync).
    Évite la saturation du pool sous charge (1000+ webhooks/min).

    Returns:
        True si le message est un doublon (à ignorer).
        False si c'est la première occurrence (à traiter).
    """
    if not msg_id:
        return False
    try:
        r = await _get_async_redis()
        if not r:
            return False
        key = f"{_WA_DEDUP_PREFIX}{store_id}:{msg_id}"
        # SET NX (set si non existant) — retourne True si la clé a été créée (premier passage)
        was_new = await r.set(key, "1", nx=True, ex=_WA_DEDUP_TTL_SECONDS)
        if not was_new:
            logger.info(
                "whatsapp.webhook.dedup_skip store_id=%s msg_id=%s",
                store_id,
                msg_id,
            )
            return True
        return False
    except Exception as exc:
        logger.warning(
            "whatsapp.webhook.dedup_error store_id=%s msg_id=%s error=%s",
            store_id,
            msg_id,
            str(exc),
        )
        # En cas d'erreur Redis, on laisse passer (fail open) pour ne pas
        # bloquer les messages légitimes.
        return False


# ─── Plan gate dependency ──────────────────────────────────────────────────────
async def _require_whatsapp_plan() -> None:
    """Raises 403 if the current tenant is not on the pro_whatsapp plan."""
    from security_overlay.billing_overlay import get_billing_snapshot

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")
    snapshot = await get_billing_snapshot(int(store_id))
    if not snapshot.has_feature("channels.whatsapp"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "whatsapp_plan_required",
                "message": (
                    "WhatsApp est disponible uniquement avec le plan "
                    "Pro WhatsApp (49,99 DT/mois). "
                    "Les frais Meta WhatsApp ne sont pas inclus."
                ),
                "required_plan": "pro_whatsapp",
                "current_plan": snapshot.plan_code,
            },
        )


# ─── Webhook verification (GET) ───────────────────────────────────────────────
from api.v1._deps import get_store_id as _sid


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        # P0 FIX: Meta sends an arbitrary string for hub.challenge — DO NOT cast to int.
        # Echo back the raw value as plain text (Meta requirement).
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


# ─── Incoming messages (POST) ─────────────────────────────────────────────────
@router.post("/webhook")
async def receive_webhook(
    request: Request,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    # Signature verification
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    if not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")

    if not settings.WHATSAPP_APP_SECRET:
        raise HTTPException(status_code=503, detail="WhatsApp APP_SECRET not configured")

    expected = hmac.HMAC(
        settings.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_header.removeprefix("sha256="), expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    data = json.loads(body)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue

            val = change["value"]
            phone_number_id = val.get("metadata", {}).get("phone_number_id")

            # P0-4: Resolve store_id from phone_number_id via DB
            store_id = await _resolve_store_id(db, phone_number_id)
            if store_id is None:
                logger.warning(
                    "Unknown phone_number_id='%s'. "
                    "Register via POST /api/v1/whatsapp/register-phone",
                    phone_number_id,
                )
                continue  # Never return 4xx to Meta

            for msg in val.get("messages", []):
                from_phone = msg.get("from")
                msg_id = msg.get("id")
                msg_type = msg.get("type")

                # ── FIX v20.3 — Anti-double réponse WhatsApp ───────────────────
                # Meta peut retransmettre le même webhook plusieurs fois.
                # On déduplique via Redis SET NX avant tout traitement.
                if await _is_duplicate_wa_message(msg_id, store_id):
                    continue

                payload: dict = _build_canonical_payload(
                    msg=msg,
                    store_id=store_id,
                    phone_number_id=phone_number_id,
                )

                # A7-FIX : Ignorer les events non-commerciaux AVANT de déclencher Celery.
                # sticker/reaction/read/delivery ne nécessitent aucune réponse IA.
                _NON_LLM_TYPES = {"sticker", "reaction", "read_receipt", "delivery_receipt"}
                if msg_type in _NON_LLM_TYPES:
                    logger.debug("skip_llm_non_text type=%s", msg_type)
                    continue

                if msg_type == "text":
                    # HIGH-11 FIX: limiter la taille du texte avant l'appel LLM.
                    _raw_body = msg["text"]["body"]
                    _MAX_LEN = getattr(settings, "MAX_INPUT_LENGTH", 2000)
                    if len(_raw_body) > _MAX_LEN:
                        logger.warning(
                            "WhatsApp message truncated: %d chars -> %d (store_id=%s, from=%s)",
                            len(_raw_body), _MAX_LEN, store_id, from_phone,
                        )
                        _raw_body = _raw_body[:_MAX_LEN]
                    payload["body"] = _raw_body
                    payload["text"] = _raw_body

                elif msg_type in ("image", "document"):
                    media_data = msg.get(msg_type, {})
                    payload["media_id"] = media_data.get("id")
                    payload["mime_type"] = media_data.get("mime_type")

                elif msg_type == "audio":
                    payload["media_id"] = msg["audio"]["id"]
                    payload["mime_type"] = msg.get("audio", {}).get("mime_type")

                elif msg_type == "interactive":
                    # P0-6: properly route button and list replies
                    interactive = msg.get("interactive", {})
                    itype = interactive.get("type")
                    if itype == "button_reply":
                        payload["type"] = "interactive"
                        payload["message_type"] = "interactive"
                        payload["button_id"] = interactive["button_reply"]["id"]
                        payload["button_title"] = interactive["button_reply"].get("title", "")
                    elif itype == "list_reply":
                        payload["type"] = "interactive"
                        payload["message_type"] = "interactive"
                        payload["button_id"] = interactive["list_reply"]["id"]
                        payload["button_title"] = interactive["list_reply"].get("title", "")
                    else:
                        logger.debug("Unknown interactive type: %s", itype)
                        continue

                elif msg_type == "location":
                    loc = msg.get("location", {})
                    payload["latitude"] = loc.get("latitude")
                    payload["longitude"] = loc.get("longitude")
                    payload["location"] = dict(loc)

                else:
                    logger.debug("Unhandled WA message type: %s", msg_type)
                    continue

                # ── Contrôle IA : sourdine / prise de main ─────────────────────────
                _from_phone = msg.get("from", "")
                try:
                    from services.agent_mute import should_ai_respond as _should_ai_respond
                    _should_respond, _mute_reason = await _should_ai_respond(store_id, _from_phone)
                    if not _should_respond:
                        logger.info(
                            "agent_mute: IA silencieuse store=%s phone=%.6s*** reason=%s",
                            store_id, _from_phone, _mute_reason
                        )
                        continue  # ne pas répondre — marchand en prise de main
                except Exception as _me:
                    logger.warning("agent_mute check failed — defaulting to respond: %s", _me)

                # ── BLOC 10 — Dispatcher V9 complet (remplace V8) ─────────────
                # Si OMNICALL_V9_ENABLED=1 et le store est dans le rollout :
                #   → V9 prend en charge le message de bout en bout (pipeline + LLM + envoi)
                #   → V8 (process_whatsapp_message) N'EST PAS appelé
                # Sinon : fallback V8 (comportement identique à avant BLOC 10)
                # En cas d'échec V9 : DispatchResult.dispatched_by_v9=False → V8 prend le relais.

                decision = get_active_route_decision(store_id)

                # Phase 6 — Métriques webhook
                _metrics.webhook_events_total.labels(
                    channel="whatsapp", event_type=payload.get("type", "text")
                ).inc()

                # Phase 2 — Redis Streams (non-bloquant, fail-safe)
                bg.add_task(_push_to_stream, dict(payload), store_id)

                if decision.active:
                    # ── V9 actif : dispatch complet (BLOC 10) ──────────────────
                    bg.add_task(
                        _bloc10_dispatch_task,
                        dict(payload),
                        "whatsapp",
                        store_id,
                    )
                else:
                    # ── V8 fallback + Shadow Mode V9 (BLOC 7) ──────────────────
                    process_whatsapp_message.delay(
                        store_id=store_id,
                        customer_phone=payload.get("from", ""),
                        message_text=payload.get("text") or payload.get("body") or "",
                    )
                    bg.add_task(_shadow_v9_task, dict(payload), "whatsapp", store_id)

            for status in val.get("statuses", []):
                logger.debug("WA status: %s msg=%s", status.get("status"), status.get("id"))

    return {"status": "received"}


async def _push_to_stream(payload: dict, store_id: int | None) -> None:
    """Phase 2 — Pousse le message dans Redis Streams de façon non-bloquante.

    Fail-safe : si Redis est indisponible, l'opération est silencieusement
    ignorée — Celery a déjà été dispatché via route_to_v9_if_enabled.
    """
    try:
        stream_payload = {
            "message_id": payload.get("id") or payload.get("message_id", ""),
            "store_id": str(store_id or ""),
            "from_phone": payload.get("from", ""),
            "body": payload.get("body") or payload.get("text") or "",
            "type": payload.get("type", "text"),
        }
        await _mq.push_message(stream_payload)
        _metrics.redis_operations_total.labels(operation="xadd", outcome="ok").inc()
    except Exception as exc:
        _metrics.redis_operations_total.labels(operation="xadd", outcome="error").inc()
        logger.warning("_push_to_stream failed (non-blocking): %s", exc)


async def _bloc10_dispatch_task(payload: dict, channel: str, store_id: int | None) -> None:
    """BLOC 10 — Dispatch complet V9 : pipeline + LLM + envoi.

    Si V9 échoue (DispatchResult.dispatched_by_v9=False), fallback automatique vers V8.
    Jamais de throw externe.
    """
    try:
        from sqlalchemy import select

        from models.database import AsyncSessionLocal, Customer, Store
        from omnicall_v9.bloc10 import dispatch_v9
        from omnicall_v9.normalizers.whatsapp import normalize_whatsapp_payload

        unified = normalize_whatsapp_payload(payload)

        async with AsyncSessionLocal() as db:
            store_row = (await db.execute(
                select(Store).where(Store.id == store_id)
            )).scalar_one_or_none()

            if not store_row:
                logger.warning("bloc10: store_id=%s not found, V8 fallback", store_id)
                _v8_fallback(payload, store_id)
                return

            customer_row = None
            from_phone = payload.get("from", "")
            if from_phone:
                customer_row = (await db.execute(
                    select(Customer).where(
                        Customer.store_id == store_id,
                        Customer.whatsapp_phone == from_phone,
                    )
                )).scalar_one_or_none()

            result = await dispatch_v9(unified, db=db, store=store_row, customer=customer_row)

        if not result.dispatched_by_v9:
            logger.info(
                "omnicall_v9.bloc10.v8_fallback store_id=%s reason=%s",
                store_id, result.v8_fallback_reason,
            )
            _v8_fallback(payload, store_id)

    except Exception as exc:
        logger.error(
            "omnicall_v9.bloc10.task_failed store_id=%s error=%s",
            store_id, exc,
        )
        _v8_fallback(payload, store_id)


def _v8_fallback(payload: dict, store_id: int | None) -> None:
    """Appelle la tâche Celery V8 comme fallback."""
    try:
        process_whatsapp_message.delay(
            store_id=store_id,
            customer_phone=payload.get("from", ""),
            message_text=payload.get("text") or payload.get("body") or "",
        )
    except Exception as exc:
        logger.error("bloc10._v8_fallback failed store_id=%s: %s", store_id, exc)


def _shadow_v9_task(payload: dict, channel: str, store_id: int | None) -> None:
    """Tâche background non-bloquante pour le Shadow Mode V9."""
    try:
        from omnicall_v9.shadow_mode import run_shadow_v9
        run_shadow_v9(payload, channel, store_id)
    except Exception as exc:
        logger.error(
            "omnicall_v9.shadow.task_failed",
            extra={"channel": channel, "store_id": store_id, "error": str(exc)},
        )


async def _resolve_store_id(db: AsyncSession, phone_number_id: str | None) -> int | None:
    if not phone_number_id:
        return None
    result = await db.execute(
        select(StorePhoneMapping).where(
            StorePhoneMapping.phone_number_id == phone_number_id,
            StorePhoneMapping.is_active,
        )
    )
    mapping = result.scalar_one_or_none()
    return mapping.store_id if mapping else None


# ─── Phone registration endpoint ──────────────────────────────────────────────
class RegisterPhoneRequest(BaseModel):
    phone_number_id: str
    display_phone: str | None = None


@router.post("/register-phone", status_code=201, dependencies=[Depends(_require_whatsapp_plan)])
async def register_phone(body: RegisterPhoneRequest, db: AsyncSession = Depends(get_db)):
    """Link a WhatsApp phone_number_id to the current store. Call once during onboarding."""
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")
    existing = await db.execute(
        select(StorePhoneMapping).where(StorePhoneMapping.phone_number_id == body.phone_number_id)
    )
    mapping = existing.scalar_one_or_none()
    if mapping:
        if mapping.store_id != store_id:
            raise HTTPException(status_code=409, detail="phone_number_id already registered to another store")
        mapping.display_phone = body.display_phone
        mapping.is_active = True
    else:
        mapping = StorePhoneMapping(
            phone_number_id=body.phone_number_id,
            store_id=store_id,
            display_phone=body.display_phone,
        )
        db.add(mapping)
    await db.commit()
    return {
        "phone_number_id": mapping.phone_number_id,
        "store_id": mapping.store_id,
        "display_phone": mapping.display_phone,
        "status": "registered",
    }


@router.get("/registered-phones", dependencies=[Depends(_require_whatsapp_plan)])
async def list_registered_phones(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")
    result = await db.execute(
        select(StorePhoneMapping).where(
            StorePhoneMapping.store_id == store_id,
            StorePhoneMapping.is_active,
        )
    )
    return [
        {"phone_number_id": m.phone_number_id, "display_phone": m.display_phone}
        for m in result.scalars().all()
    ]


# ─── Owner phone configuration ────────────────────────────────────────────────
class SetOwnerPhoneRequest(BaseModel):
    owner_phone: str   # ex: "+21612345678"


@router.put("/owner-phone")
async def set_owner_phone(
    body: SetOwnerPhoneRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Enregistre le numéro WhatsApp du marchand comme numéro admin.
    Messages entrants de ce numéro -> mode admin conversationnel (owner_agent).
    """
    from middleware.tenant import current_tenant_id
    from models.database import Store
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.owner_phone = body.owner_phone
    await db.commit()
    return {"ok": True, "owner_phone": store.owner_phone, "message": "Mode admin WhatsApp activé"}


@router.delete("/owner-phone")
async def remove_owner_phone(db: AsyncSession = Depends(get_db)):
    """Désactive le mode admin WhatsApp pour ce store."""
    from middleware.tenant import current_tenant_id
    from models.database import Store
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.owner_phone = None
    await db.commit()
    return {"ok": True, "message": "Mode admin WhatsApp désactivé"}


# ─── Contrôle IA : sourdine globale + prise de main per-client ────────────────
# Ces 6 endpoints permettent au marchand de contrôler finement si l'IA répond.
#
# Cas d'usage :
#   1. Sourdine 30 min (POST /agent/mute)        -> tu réponds à tout le monde
#   2. Prise de main sur un client (POST /agent/takeover/{phone})
#      -> l'IA reste active pour les autres, toi tu réponds à ce client
#   3. Annulation (DELETE) -> l'IA reprend immédiatement
#   4. Status (GET)        -> voir l'état actuel

class MuteRequest(BaseModel):
    minutes: int = 30  # durée de la sourdine en minutes (1-1440)

class TakeoverRequest(BaseModel):
    minutes: int = 120  # durée de la prise de main en minutes (1-1440)


@router.post("/agent/mute")
async def mute_store_agent(
    body: MuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Met l'IA en sourdine complète pour toute la boutique pendant N minutes.
    L'IA cesse de répondre à TOUS les clients. Toi tu réponds manuellement.

    Exemples :
      - Maintenance rapide : {"minutes": 15}
      - Appel client important, pas de distraction IA : {"minutes": 60}

    L'IA reprend automatiquement après le délai, ou via DELETE /agent/mute.
    """
    from middleware.tenant import current_tenant_id
    from services.agent_mute import mute_store

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    return await mute_store(store_id, minutes=body.minutes)


@router.delete("/agent/mute")
async def unmute_store_agent(db: AsyncSession = Depends(get_db)):
    """
    Reprend l'IA immédiatement — annule la sourdine avant l'expiration.
    """
    from middleware.tenant import current_tenant_id
    from services.agent_mute import unmute_store

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    return await unmute_store(store_id)


@router.post("/agent/takeover/{customer_phone}")
async def takeover_customer_agent(
    customer_phone: str,
    body: TakeoverRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Prend la main sur UN client précis — l'IA ne lui répondra plus pendant N minutes.
    L'IA reste active pour tous les autres clients.

    Cas d'usage typique :
      - Client difficile ou VIP : tu veux répondre personnellement
      - Négociation de prix
      - SAV complexe nécessitant une réponse humaine

    customer_phone : numéro international du client (ex: 21698123456 ou +21698123456)
    """
    from middleware.tenant import current_tenant_id
    from services.agent_mute import takeover_customer

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    return await takeover_customer(store_id, customer_phone, minutes=body.minutes)


@router.delete("/agent/takeover/{customer_phone}")
async def release_customer_agent(
    customer_phone: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Rend la main à l'IA pour ce client — reprend immédiatement.
    L'IA re-prend la conversation avec ce client.
    """
    from middleware.tenant import current_tenant_id
    from services.agent_mute import release_customer

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    return await release_customer(store_id, customer_phone)


@router.get("/agent/status")
async def get_agent_status(db: AsyncSession = Depends(get_db)):
    """
    Vue complète de l'état IA pour cette boutique :
    - Mode actuel (active / muted / partial)
    - Sourdine globale (restant en minutes)
    - Liste des clients en prise de main manuelle (avec TTL)

    Exemple de réponse :
    {
      "ai_mode": "partial",
      "mute": {"active": false, "remaining_seconds": 0},
      "takeovers": [
        {"customer_phone": "21698***456", "remaining_minutes": 45}
      ],
      "summary": "IA active — 1 client(s) en prise de main manuelle"
    }
    """
    from middleware.tenant import current_tenant_id
    from services.agent_mute import get_store_agent_status

    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    return await get_store_agent_status(store_id)


# ─── Public opt-out endpoint (appelé sur STOP / ARRÊT) ────────────────────────
class OptOutRequest(BaseModel):
    from_phone: str
    store_id: int


@router.post("/opt-out", status_code=200)
async def opt_out(body: OptOutRequest, db: AsyncSession = Depends(get_db)):
    """Endpoint public — appelé quand un client envoie "STOP" ou "ARRÊT".

    Marque le client comme opted_out=True dans la DB afin qu'il soit
    exclu des prochains broadcasts et des réponses IA automatiques.
    Idempotent : si le client est déjà opted_out, retourne quand même 200.
    """
    from datetime import UTC, datetime

    from models.database import Customer

    result = await db.execute(
        select(Customer).where(
            Customer.store_id == body.store_id,
            Customer.whatsapp_phone == body.from_phone,
        )
    )
    customer = result.scalar_one_or_none()

    if not customer:
        # Client inconnu — on l'enregistre directement opted_out pour anticiper
        # une inscription future ou un envoi broadcast malencontreusement fait
        # à un numéro non encore client.
        customer = Customer(
            store_id=body.store_id,
            whatsapp_phone=body.from_phone,
            opted_out=True,
            opted_out_at=datetime.now(UTC),
        )
        db.add(customer)
        try:
            await db.commit()
        except Exception as _exc:
            logger.warning("opt_out customer_create failed: %s", _exc)
            await db.rollback()
        logger.info(
            "whatsapp.opt_out.new_customer store_id=%s phone=%.6s***",
            body.store_id, body.from_phone,
        )
        return {"status": "opted_out", "created": True}

    if not customer.opted_out:
        customer.opted_out = True
        customer.opted_out_at = datetime.now(UTC)
        try:
            await db.commit()
        except Exception as _exc:
            logger.warning("opt_out customer_update failed: %s", _exc)
            await db.rollback()

    logger.info(
        "whatsapp.opt_out store_id=%s phone=%.6s***",
        body.store_id, body.from_phone,
    )
    return {"status": "opted_out", "created": False}
