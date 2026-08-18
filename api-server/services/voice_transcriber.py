"""services/voice_transcriber.py — Transcription audio WhatsApp via Whisper.

Fonctionnalités :
  - Téléchargement média WhatsApp (audio OGG/MP4, images) via l'API Meta.
  - Transcription audio via OpenAI Whisper API (whisper-1).
  - Détection de langue automatique (fr/ar/darija).
  - Cache Redis (TTL 1h) pour éviter les re-transcriptions.
  - Fallback : retourne une chaîne vide si Whisper est indisponible.
  - _download_media() est public (utilisé par auto_parts_agent pour les images).

Interface publique :
  transcribe_whatsapp_audio(media_id, store) -> str
  _download_media(media_id, store)           -> bytes   (générique, images et audio)
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

_WA_MEDIA_URL = "https://graph.facebook.com/v19.0/{media_id}"
_WHISPER_URL  = "https://api.openai.com/v1/audio/transcriptions"
_DOWNLOAD_TIMEOUT = 20.0
_WHISPER_TIMEOUT  = 30.0
_CACHE_TTL_SECONDS = 3600  # 1 heure

# Extensions audio supportées par Whisper
_AUDIO_EXTENSIONS = {
    "audio/ogg":  ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4":  ".mp4",
    "audio/wav":  ".wav",
    "audio/webm": ".webm",
    "audio/amr":  ".amr",
    "audio/aac":  ".aac",
}


# ── Helpers Redis ─────────────────────────────────────────────────────────────

async def _cache_get(key: str) -> str | None:
    try:
        import os

        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        val = await client.get(key)
        await client.aclose()
        return val
    except Exception:
        return None


async def _cache_set(key: str, value: str) -> None:
    try:
        import os

        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        await client.setex(key, _CACHE_TTL_SECONDS, value)
        await client.aclose()
    except Exception:
        pass  # Cache non critique


# ── Téléchargement média WhatsApp ─────────────────────────────────────────────

async def _get_wa_access_token(store: Any) -> str | None:
    """Récupère le token WhatsApp Business API du store (déchiffré)."""
    token_enc = getattr(store, "whatsapp_access_token_enc", None)
    if not token_enc:
        # Fallback sur variable d'env globale
        import os
        return os.environ.get("WHATSAPP_ACCESS_TOKEN")
    try:
        from config import settings
        return settings.decrypt(token_enc)
    except Exception:
        import os
        return os.environ.get("WHATSAPP_ACCESS_TOKEN")


async def _download_media(media_id: str, store: Any | None = None) -> bytes:
    """Télécharge un média WhatsApp (audio ou image) depuis l'API Meta.

    Args:
        media_id : ID du média WhatsApp (champ media_id du webhook).
        store    : Store tenant (pour récupérer le token WA si BYOK configuré).

    Returns:
        Bytes du fichier téléchargé.

    Raises:
        httpx.HTTPStatusError : Si l'API Meta retourne une erreur.
        Exception             : Si le téléchargement échoue.
    """
    token = await _get_wa_access_token(store) if store else None
    if not token:
        import os
        token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        # Étape 1 : obtenir l'URL de téléchargement
        meta_resp = await client.get(
            _WA_MEDIA_URL.format(media_id=media_id),
            headers=headers,
        )
        meta_resp.raise_for_status()
        media_data = meta_resp.json()
        download_url = media_data.get("url")

        if not download_url:
            raise ValueError(f"No download URL for media_id={media_id}")

        # Étape 2 : télécharger le fichier
        file_resp = await client.get(download_url, headers=headers)
        file_resp.raise_for_status()

        logger.info(
            "Downloaded media_id=%s size=%d bytes content_type=%s",
            media_id, len(file_resp.content),
            file_resp.headers.get("content-type", "unknown"),
        )
        return file_resp.content


# ── Transcription Whisper ─────────────────────────────────────────────────────

async def _transcribe_bytes(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    language_hint: str | None = None,
) -> str:
    """Transcrit des bytes audio via OpenAI Whisper API.

    Args:
        audio_bytes   : Bytes du fichier audio.
        mime_type     : Type MIME (ex: "audio/ogg").
        language_hint : Code langue ISO (ex: "fr", "ar") pour améliorer la précision.

    Returns:
        Texte transcrit (chaîne vide si échec).
    """
    import os

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — Whisper transcription unavailable")
        return ""

    ext = _AUDIO_EXTENSIONS.get(mime_type, ".ogg")

    # Écrire dans un fichier temporaire (Whisper API exige un fichier nommé)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)

    try:
        async with httpx.AsyncClient(timeout=_WHISPER_TIMEOUT) as client:
            with open(tmp_path, "rb") as f:
                files = {"file": (f"audio{ext}", f, mime_type)}
                data: dict[str, str] = {
                    "model": "whisper-1",
                    "response_format": "json",
                }
                if language_hint:
                    data["language"] = language_hint

                resp = await client.post(
                    _WHISPER_URL,
                    headers={"Authorization": f"Bearer {openai_key}"},
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                result = resp.json()
                text = result.get("text", "").strip()
                logger.info(
                    "Whisper transcription: %d chars (lang=%s)",
                    len(text), language_hint or "auto",
                )
                return text

    except httpx.HTTPStatusError as exc:
        logger.error("Whisper API HTTP %s: %s", exc.response.status_code, exc)
        return ""
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return ""
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Point d'entrée principal ──────────────────────────────────────────────────

async def transcribe_whatsapp_audio(
    media_id: str,
    store: Any | None = None,
    mime_type: str = "audio/ogg",
    language_hint: str | None = None,
) -> str:
    """Transcrit un message vocal WhatsApp en texte.

    Stratégie :
      1. Vérifie le cache Redis (clé = media_id).
      2. Télécharge le fichier audio depuis l'API Meta.
      3. Transcrit via Whisper API.
      4. Met en cache le résultat (TTL 1h).
      5. Fallback : retourne "" si Whisper est indisponible.

    Args:
        media_id      : ID du média WhatsApp.
        store         : Store tenant (pour token BYOK).
        mime_type     : Type MIME du média (défaut : audio/ogg pour WA vocal).
        language_hint : Langue attendue ("fr" | "ar" | None = autodetect).

    Returns:
        Texte transcrit ou chaîne vide en cas d'échec.
    """
    cache_key = f"whisper:transcript:{media_id}"

    # 1. Cache hit ?
    cached = await _cache_get(cache_key)
    if cached is not None:
        logger.debug("Whisper cache hit for media_id=%s", media_id)
        return cached

    # 2. Télécharger
    try:
        audio_bytes = await _download_media(media_id, store)
    except Exception as exc:
        logger.error("Failed to download audio media_id=%s: %s", media_id, exc)
        return ""

    if not audio_bytes:
        return ""

    # 3. Transcrire
    text = await _transcribe_bytes(audio_bytes, mime_type, language_hint)

    # 4. Mettre en cache
    if text:
        await _cache_set(cache_key, text)

    return text


# ── Détection de langue simple (heuristique) ──────────────────────────────────

def detect_language_hint(text: str) -> str | None:
    """Heuristique rapide pour deviner la langue d'un texte court.

    Retourne "ar" si le texte contient des caractères arabes,
    "fr" si dominance de mots français, None sinon (Whisper autodetect).
    """
    if not text:
        return None
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    if arabic_chars > len(text) * 0.3:
        return "ar"
    french_markers = {"le", "la", "les", "de", "du", "je", "tu", "il", "elle", "nous", "vous", "bonjour", "merci"}
    words = set(text.lower().split())
    if len(words & french_markers) >= 2:
        return "fr"
    return None
