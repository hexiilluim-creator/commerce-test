"""services/vision_analyzer.py — Analyse d'images via IA."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from config import settings
from services.openai_resolver import get_platform_client, resolve_openai_client

logger = logging.getLogger(__name__)

DEFAULT_VISION_RESULT = {
    "name": "",
    "description": "",
    "category": "other",
    "price_hint": None,
    "tags": [],
}

VISION_SYSTEM_PROMPT = (
    'Tu es un assistant e-commerce. Analyse cette image de produit. '
    'Retourne UNIQUEMENT du JSON valide : '
    '{"name": str, "description": str, "category": str, '
    '"price_hint": float|null, "tags": list[str]}'
)


def _guess_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "image/jpeg"


def _extract_text_content(response: Any) -> str:
    try:
        return (response.choices[0].message.content or "").strip()
    except Exception as _exc:
        logger.warning("_extract_text_content failed: %s", _exc)
        return ""


def _clean_json_payload(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def _coerce_result(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return DEFAULT_VISION_RESULT.copy()

    price_hint = payload.get("price_hint")
    if price_hint in ("", "null"):
        price_hint = None
    elif price_hint is not None:
        try:
            price_hint = float(price_hint)
        except (TypeError, ValueError):
            price_hint = None

    tags = payload.get("tags")
    if not isinstance(tags, list):
        tags = []
    else:
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]

    return {
        "name": str(payload.get("name") or ""),
        "description": str(payload.get("description") or ""),
        "category": str(payload.get("category") or "other"),
        "price_hint": price_hint,
        "tags": tags,
    }


async def analyze_image_bytes(data: bytes, store_id: int | None = None, db=None) -> dict:
    """Analyse une image produit via GPT-4o Vision et retourne un JSON normalisé."""
    image_base64 = base64.b64encode(data).decode("utf-8")
    media_type = _guess_media_type(data)

    try:
        client = await resolve_openai_client(store_id, db) if store_id is not None else get_platform_client()
        async with asyncio.timeout(30):
            response = await client.chat.completions.create(
                model=getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o"),
                temperature=0,
                max_tokens=400,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyse cette image produit et retourne uniquement le JSON demandé."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_base64}",
                                },
                            },
                        ],
                    },
                ],
            )
        raw_text = _extract_text_content(response)
        payload = json.loads(_clean_json_payload(raw_text))
        return _coerce_result(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Impossible de parser la réponse vision en JSON valide")
        return DEFAULT_VISION_RESULT.copy()
    except TimeoutError:
        logger.warning("Timeout pendant l'analyse vision (30s)")
        return DEFAULT_VISION_RESULT.copy()
    except Exception as exc:
        logger.exception("Erreur d'analyse d'image: %s", exc)
        return DEFAULT_VISION_RESULT.copy()


async def analyze_image_base64(image_base64: str, media_type: str, prompt: str, store_id: int, db) -> str:
    """Version texte libre: retourne la réponse brute du LLM (scan facture, OCR assisté, etc.)."""
    client = await resolve_openai_client(store_id, db)
    async with asyncio.timeout(30):
        response = await client.chat.completions.create(
            model=getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o"),
            temperature=0,
            max_tokens=1200,
            messages=[
                {"role": "system", "content": "Tu analyses des images et des documents visuels avec précision."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_base64}",
                            },
                        },
                    ],
                },
            ],
        )
    return _extract_text_content(response)


async def analyze_image_url(url: str, store_id: int | None = None, db=None) -> dict:
    """Télécharge l'image puis délègue à analyze_image_bytes."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return await analyze_image_bytes(response.content, store_id=store_id, db=db)


# ── Compat alias — requis par services/ai_agent.py (BLOQUANT B3-A) ────────────

async def analyze_whatsapp_image(
    media_id: str,
    store: object | None = None,
    db: object | None = None,
) -> dict:
    """Télécharge un média WhatsApp par media_id et l'analyse via LLM vision.

    Alias de haut niveau utilisé par ai_agent.py pour analyser les images
    envoyées par les clients WhatsApp.

    Retourne un dict compatible avec analyze_image_bytes :
      {
        "type":        str,    # "product" | "document" | "scene" | "text" | "unknown"
        "description": str,
        "confidence":  float,
        "raw_text":    str | None,
        "found":       bool,
        "product_hints": list[str],
      }
    """
    try:
        from services.voice_transcriber import _download_media
        image_bytes = await _download_media(media_id, store)
        if not image_bytes:
            return {"type": "unknown", "description": "", "confidence": 0.0,
                    "found": False, "product_hints": [], "raw_text": None}
        store_id = getattr(store, "id", None) if store else None
        return await analyze_image_bytes(image_bytes, store_id=store_id, db=db)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "analyze_whatsapp_image failed media_id=%s: %s", media_id, exc
        )
        return {"type": "unknown", "description": "", "confidence": 0.0,
                "found": False, "product_hints": [], "raw_text": None}
