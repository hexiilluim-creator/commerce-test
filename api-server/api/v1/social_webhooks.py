"""api/v1/social_webhooks.py — Webhooks entrants Instagram / Facebook / TikTok.

Overlay security updates:
- social signatures: signed -> fail closed, unsigned -> fail open contrôlé
- workflow_events persistence for received / validated / rejected / replayed / queued
- webhook deduplication / idempotency
- Celery-backed retries for social processing
- Prometheus webhook metrics
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from config import settings
from models.database import AsyncSessionLocal
from omnicall_v9.active_router import get_active_route_decision, route_to_v9_if_enabled
from services.metrics import (
    webhook_events_total,
    webhook_inflight,
    webhook_processing_duration_seconds,
)
from services.store_resolver import resolve_store_id_from_social_id
from services.tasks import process_social_webhook
from services.webhook_reliability import claim_webhook_message
from services.workflow_events import record_workflow_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/social", tags=["Social Webhooks"])


async def _record_social_event(
    *,
    channel: str,
    status: str,
    store_id: int | None,
    payload: dict[str, object],
    signature_status: str | None,
    error_message: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        await record_workflow_event(
            db,
            workflow_type="social_webhook",
            status=status,
            provider=channel,
            channel=channel,
            tenant_id=store_id,
            external_event_id=payload.get("message_id"),
            message_id=payload.get("message_id"),
            signature_status=signature_status,
            payload_json=payload,
            error_message=error_message,
            retryable=status == "failed",
            dlq_name="social.dlq" if status == "failed" else None,
        )
        await db.commit()


async def _reject_social_webhook(
    *,
    channel: str,
    store_id: int | None,
    payload: dict[str, object],
    signature_status: str,
    detail: str,
) -> None:
    await _record_social_event(
        channel=channel,
        status="rejected",
        store_id=store_id,
        payload=payload,
        signature_status=signature_status,
        error_message=detail,
    )
    raise HTTPException(status_code=401, detail=detail)


async def _record_invalid_json(channel: str, raw: bytes) -> None:
    await _record_social_event(
        channel=channel,
        status="rejected",
        store_id=None,
        payload={"raw": raw.decode(errors="ignore")[:1000]},
        signature_status="invalid_json",
        error_message="Invalid JSON",
    )


async def _validate_optional_signature(channel: str, body: bytes, secret: str, header_value: str) -> str:
    if not secret:
        # No secret configured for this tenant/channel: cannot validate at all.
        # Accepted but flagged so it stays visible in workflow_events/metrics.
        return "unsigned"
    if not header_value:
        # Secret IS configured but no signature header was sent: this is not
        # "unsigned", it's a spoofing attempt against a channel that expects
        # signatures. Fail closed.
        raise HTTPException(status_code=401, detail=f"Missing {channel.title()} signature")
    expected = hmac.HMAC(secret.encode(), body, hashlib.sha256).hexdigest()
    candidate = header_value.removeprefix("sha256=")
    if not hmac.compare_digest(candidate, expected):
        raise HTTPException(status_code=401, detail=f"Invalid {channel.title()} signature")
    return "validated"


async def _validate_tiktok_signature(body: bytes, secret: str, header_value: str) -> str:
    if not secret:
        return "unsigned"
    if not header_value:
        raise HTTPException(status_code=401, detail="Missing TikTok signature")
    expected = hmac.HMAC(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(header_value, expected):
        raise HTTPException(status_code=401, detail="Invalid TikTok signature")
    return "validated"


async def _dedupe_or_skip(
    *,
    channel: str,
    store_id: int | None,
    payload: dict[str, object],
    signature_status: str,
) -> bool:
    is_first_delivery = await claim_webhook_message(
        channel=channel,
        store_id=store_id,
        message_id=payload.get("message_id"),
        sender_id=payload.get("sender_id"),
        recipient_id=payload.get("recipient_id"),
        body=payload.get("body"),
    )
    if not is_first_delivery:
        webhook_events_total.labels(channel=channel, event_type="duplicate").inc()
        logger.info(
            "social.webhook.duplicate_skipped channel=%s store_id=%s message_id=%s",
            channel,
            store_id,
            payload.get("message_id"),
        )
        await _record_social_event(
            channel=channel,
            status="replayed",
            store_id=store_id,
            payload=payload,
            signature_status=signature_status,
            error_message="duplicate_delivery",
        )
        return True
    return False


def _extract_meta_attachments(message: dict[str, object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for item in message.get("attachments") or []:
        payload = item.get("payload") or {}
        normalized.append(
            {
                "media_id": payload.get("attachment_id") or item.get("id"),
                "url": payload.get("url"),
                "mime_type": item.get("mime_type") or item.get("type"),
                "caption": payload.get("title") or item.get("title"),
            }
        )
    return [item for item in normalized if item.get("media_id") or item.get("url")]


def _enqueue_social_task(payload: dict[str, object], channel: str, store_id: int | None, active: bool) -> None:
    process_social_webhook.delay(dict(payload), channel, store_id, active)


def _observe_webhook_request(channel: str, started_at: float, outcome: str) -> None:
    duration = max(0.0, time.perf_counter() - started_at)
    webhook_processing_duration_seconds.labels(channel=channel, outcome=outcome).observe(duration)
    webhook_inflight.labels(channel=channel).dec()


@router.get("/instagram/webhook")
async def verify_instagram_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.INSTAGRAM_VERIFY_TOKEN:
        logger.info("Instagram webhook verified")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    raise HTTPException(status_code=403, detail="Instagram webhook verification failed")


@router.post("/instagram/webhook")
async def receive_instagram_webhook(request: Request, bg: BackgroundTasks):
    started_at = time.perf_counter()
    outcome = "success"
    webhook_inflight.labels(channel="instagram").inc()

    try:
        body = await request.body()
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        try:
            signature_status = await _validate_optional_signature("instagram", body, settings.INSTAGRAM_APP_SECRET, sig_header)
        except HTTPException as exc:
            outcome = "error"
            webhook_events_total.labels(channel="instagram", event_type="error").inc()
            await _reject_social_webhook(channel="instagram", store_id=None, payload={"raw": body.decode(errors="ignore")[:1000]}, signature_status="rejected", detail=str(exc.detail))
            raise
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            outcome = "error"
            webhook_events_total.labels(channel="instagram", event_type="error").inc()
            await _record_invalid_json("instagram", body)
            raise HTTPException(status_code=400, detail="Invalid JSON")

        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = (messaging.get("sender") or {}).get("id")
                recipient_id = (messaging.get("recipient") or {}).get("id")
                message = messaging.get("message") or {}
                attachments = _extract_meta_attachments(message)
                store_id = await resolve_store_id_from_social_id(recipient_id, "instagram")
                payload = {
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "message_id": message.get("mid"),
                    "type": "image" if attachments else "text",
                    "body": message.get("text"),
                    "attachments": attachments,
                    "raw": messaging,
                }
                webhook_events_total.labels(channel="instagram", event_type="received").inc()
                await _record_social_event(channel="instagram", status="received", store_id=store_id, payload=payload, signature_status=signature_status)
                if await _dedupe_or_skip(channel="instagram", store_id=store_id, payload=payload, signature_status=signature_status):
                    continue
                decision = get_active_route_decision(store_id)
                route_to_v9_if_enabled(payload, "instagram", store_id, logger.debug, "instagram.v8_fallback.active", decision=decision)
                bg.add_task(_enqueue_social_task, dict(payload), "instagram", store_id, decision.active)
                webhook_events_total.labels(channel="instagram", event_type="queued").inc()
                await _record_social_event(channel="instagram", status="queued", store_id=store_id, payload=payload, signature_status=signature_status)
        return {"status": "received"}
    finally:
        _observe_webhook_request("instagram", started_at, outcome)


@router.get("/facebook/webhook")
async def verify_facebook_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN:
        logger.info("Facebook webhook verified")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    raise HTTPException(status_code=403, detail="Facebook webhook verification failed")


@router.post("/facebook/webhook")
async def receive_facebook_webhook(request: Request, bg: BackgroundTasks):
    started_at = time.perf_counter()
    outcome = "success"
    webhook_inflight.labels(channel="facebook").inc()

    try:
        body = await request.body()
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        try:
            signature_status = await _validate_optional_signature("facebook", body, settings.FACEBOOK_APP_SECRET, sig_header)
        except HTTPException as exc:
            outcome = "error"
            webhook_events_total.labels(channel="facebook", event_type="error").inc()
            await _reject_social_webhook(channel="facebook", store_id=None, payload={"raw": body.decode(errors="ignore")[:1000]}, signature_status="rejected", detail=str(exc.detail))
            raise
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            outcome = "error"
            webhook_events_total.labels(channel="facebook", event_type="error").inc()
            await _record_invalid_json("facebook", body)
            raise HTTPException(status_code=400, detail="Invalid JSON")

        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = (messaging.get("sender") or {}).get("id")
                recipient_id = (messaging.get("recipient") or {}).get("id")
                message = messaging.get("message") or {}
                attachments = _extract_meta_attachments(message)
                store_id = await resolve_store_id_from_social_id(recipient_id, "facebook")
                payload = {
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "message_id": message.get("mid"),
                    "type": "image" if attachments else "text",
                    "body": message.get("text"),
                    "attachments": attachments,
                    "raw": messaging,
                }
                webhook_events_total.labels(channel="facebook", event_type="received").inc()
                await _record_social_event(channel="facebook", status="received", store_id=store_id, payload=payload, signature_status=signature_status)
                if await _dedupe_or_skip(channel="facebook", store_id=store_id, payload=payload, signature_status=signature_status):
                    continue
                decision = get_active_route_decision(store_id)
                route_to_v9_if_enabled(payload, "facebook", store_id, logger.debug, "facebook.v8_fallback.active", decision=decision)
                bg.add_task(_enqueue_social_task, dict(payload), "facebook", store_id, decision.active)
                webhook_events_total.labels(channel="facebook", event_type="queued").inc()
                await _record_social_event(channel="facebook", status="queued", store_id=store_id, payload=payload, signature_status=signature_status)
        return {"status": "received"}
    finally:
        _observe_webhook_request("facebook", started_at, outcome)


@router.get("/tiktok/webhook")
async def verify_tiktok_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    if not settings.TIKTOK_ENABLED:
        raise HTTPException(status_code=503, detail="TikTok integration disabled")
    if hub_mode == "subscribe" and hub_verify_token == settings.TIKTOK_VERIFY_TOKEN:
        logger.info("TikTok webhook verified")
        return PlainTextResponse(content=hub_challenge or "ok", status_code=200)
    raise HTTPException(status_code=403, detail="TikTok webhook verification failed")


@router.post("/tiktok/webhook")
async def receive_tiktok_webhook(request: Request, bg: BackgroundTasks):
    started_at = time.perf_counter()
    outcome = "success"
    webhook_inflight.labels(channel="tiktok").inc()

    try:
        if not settings.TIKTOK_ENABLED:
            outcome = "disabled"
            webhook_events_total.labels(channel="tiktok", event_type="disabled").inc()
            return {"status": "disabled"}

        body = await request.body()
        sig_header = request.headers.get("X-TikTok-Signature", "")
        try:
            signature_status = await _validate_tiktok_signature(body, settings.TIKTOK_APP_SECRET, sig_header)
        except HTTPException as exc:
            outcome = "error"
            webhook_events_total.labels(channel="tiktok", event_type="error").inc()
            await _reject_social_webhook(channel="tiktok", store_id=None, payload={"raw": body.decode(errors="ignore")[:1000]}, signature_status="rejected", detail=str(exc.detail))
            raise
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            outcome = "error"
            webhook_events_total.labels(channel="tiktok", event_type="error").inc()
            await _record_invalid_json("tiktok", body)
            raise HTTPException(status_code=400, detail="Invalid JSON")

        sender_id = data.get("sender", {}).get("open_id") or data.get("open_id")
        recipient_id = data.get("recipient", {}).get("open_id") or data.get("business_account_id")
        message_data = data.get("message") or {}
        store_id = await resolve_store_id_from_social_id(recipient_id, "tiktok")
        payload = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "message_id": message_data.get("message_id") or data.get("message_id"),
            "type": "text",
            "body": message_data.get("content") or data.get("content"),
            "raw": data,
        }
        webhook_events_total.labels(channel="tiktok", event_type="received").inc()
        await _record_social_event(channel="tiktok", status="received", store_id=store_id, payload=payload, signature_status=signature_status)
        if await _dedupe_or_skip(channel="tiktok", store_id=store_id, payload=payload, signature_status=signature_status):
            return {"status": "received"}
        decision = get_active_route_decision(store_id)
        route_to_v9_if_enabled(payload, "tiktok", store_id, logger.debug, "tiktok.v8_fallback.active", decision=decision)
        bg.add_task(_enqueue_social_task, dict(payload), "tiktok", store_id, decision.active)
        webhook_events_total.labels(channel="tiktok", event_type="queued").inc()
        await _record_social_event(channel="tiktok", status="queued", store_id=store_id, payload=payload, signature_status=signature_status)
        return {"status": "received"}
    finally:
        _observe_webhook_request("tiktok", started_at, outcome)


@router.get("/webhook")
async def verify_social_webhook_compat(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    valid_tokens = {
        getattr(settings, "INSTAGRAM_VERIFY_TOKEN", None),
        getattr(settings, "FACEBOOK_VERIFY_TOKEN", None),
        getattr(settings, "WHATSAPP_VERIFY_TOKEN", None),
        getattr(settings, "TIKTOK_VERIFY_TOKEN", None) if settings.TIKTOK_ENABLED else None,
    }
    if hub_mode == "subscribe" and hub_verify_token in valid_tokens and hub_challenge:
        return int(hub_challenge) if hub_challenge.isdigit() else hub_challenge
    raise HTTPException(status_code=403, detail="Social webhook verification failed")


@router.post("/webhook")
async def receive_social_webhook_compat(request: Request):
    try:
        body = await request.json()
    except Exception as _exc:
        logger.warning("receive_social_webhook_compat json_parse failed: %s", _exc)
        body = None
    logger.info(
        "social.webhook.compat.received body_keys=%s",
        list(body.keys()) if isinstance(body, dict) else None,
    )
    return {"status": "received"}
