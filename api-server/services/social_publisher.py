
# P0.5 FIX: No direct AsyncOpenAI instantiation — use central resolver
# All AI calls must go through services/openai_resolver.py for BYOK support
from services.openai_resolver import get_platform_client

"""
services/social_publisher.py — IA Sociale : DALL-E + GPT + publication multi-réseau
=====================================================================================

Flux complet :
  1. GPT-4o génère la légende (voix de marque, langue, hashtags)
  2. DALL-E 3 génère l'image (style personnalisé par store)
  3. Publication sur Instagram / Facebook / TikTok via leurs APIs
  4. Enregistrement dans social_posts (historique + statut)
  5. Scheduling Celery pour publication différée

Config par store dans SocialPostConfig :
  - brand_voice : "professionnel" | "décontracté" | "urgent" | "festif" | "inspirant"
  - image_style : prompt de style DALL-E (ex: "flat lay, white background, luxury feel")
  - default_language : "fr" | "ar" | "darija"
  - hashtags : liste personnalisée
  - post_times / post_days : planning automatique
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    SocialPost,
    SocialPostConfig,
    Store,
)

logger = logging.getLogger(__name__)
# Client OpenAI résolu à la demande via BYOK helper (par tenant courant).


# ─── Caption generation ───────────────────────────────────────────────────────

CAPTION_SYSTEM = """Tu es un expert en marketing digital pour les PME tunisiennes.
Tu crées des publications percutantes pour Instagram, Facebook et TikTok.
Tu connais la culture tunisienne et adaptes le contenu selon la langue demandée."""

CAPTION_USER = """Génère une publication {post_type} pour {network} avec ces paramètres :

Sujet : {topic}
Boutique : {brand_name}
Voix de marque : {brand_voice}
Langue : {language_label}
Style emoji : {emoji_style}
Hashtags à inclure : {hashtags}
from typing import Type : {post_type}

Règles strictes :
- Instagram/post : 150-250 mots + hashtags en bas
- Facebook/post : 80-150 mots + 1 lien si fourni
- Story : 1-2 phrases courtes et percutantes + emoji
- TikTok : 50-100 mots + trending hashtags TikTok
- Darija : mélange naturel arabe-français (ex: "c'est walo yjib ❤️")
- Toujours un call-to-action WhatsApp à la fin
- NE JAMAIS inventer de prix ou de stock

Retourne UNIQUEMENT le texte de la publication, rien d'autre."""


async def generate_caption(
    topic: str,
    network: str,
    post_type: str,
    config: SocialPostConfig | None,
    store_name: str,
    extra_context: str = "",
) -> str:
    """Génère une légende marketing via GPT-4o selon les préférences du store."""
    lang = config.default_language if config else "fr"
    voice = config.brand_voice if config else "professionnel"
    hashtags_raw = config.hashtags if config else "[]"
    emoji_style = config.emoji_style if config else "moderate"
    brand_name = config.brand_name if config else store_name

    try:
        hashtags_list = json.loads(hashtags_raw) if hashtags_raw else []
    except Exception as _exc:
        logger.warning("generate_caption failed: %s", _exc)
        hashtags_list = []

    hashtags_str = " ".join(hashtags_list) if hashtags_list else "#Tunisie #shopping #boutique"

    lang_labels = {
        "fr": "Français",
        "ar": "Arabe classique",
        "darija": "Darija tunisienne (mélange arabe-français)",
    }

    full_topic = topic
    if extra_context:
        full_topic = f"{topic}\n\nContexte : {extra_context}"

    try:
        _openai = get_platform_client()
        resp = await _openai.chat.completions.create(
            model="gpt-4o",
            max_tokens=600,
            temperature=0.82,
            messages=[
                {"role": "system", "content": CAPTION_SYSTEM},
                {"role": "user", "content": CAPTION_USER.format(
                    topic=full_topic,
                    network=network,
                    post_type=post_type,
                    brand_name=brand_name,
                    brand_voice=voice,
                    language_label=lang_labels.get(lang, "Français"),
                    emoji_style=emoji_style,
                    hashtags=hashtags_str,
                )},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Caption generation error: {e}")
        return f"🛍️ {topic}\n\nContactez-nous sur WhatsApp ! 💬\n{hashtags_str}"


# ─── DALL-E 3 image generation ────────────────────────────────────────────────

DALLE_SYSTEM_PREFIX = (
    "Create a professional marketing image for a Tunisian e-commerce store. "
    "The image must be suitable for social media (Instagram, Facebook). "
    "No text overlay. High quality, realistic, commercially appealing. "
)


async def generate_image_dalle(
    topic: str,
    config: SocialPostConfig | None,
    size: str = "1024x1024",
) -> tuple[str, str]:
    """
    Génère une image via DALL-E 3.
    Retourne (image_url, prompt_utilisé).
    image_url = URL temporaire OpenAI (valable 1h) — à re-héberger si besoin.
    """
    image_style = config.image_style if config else "commercial product photo, clean white background, professional lighting, studio quality"
    colors = config.image_colors if config else ""
    watermark = config.watermark_text if config else ""

    color_hint = f"Color palette: {colors}. " if colors else ""
    watermark_hint = f"Add subtle text '{watermark}' in corner. " if watermark else ""

    prompt = (
        f"{DALLE_SYSTEM_PREFIX}"
        f"Subject: {topic}. "
        f"Style: {image_style}. "
        f"{color_hint}"
        f"{watermark_hint}"
        f"Aspect ratio: square."
    )

    # Limiter la taille du prompt DALL-E (max 4000 chars)
    prompt = prompt[:3900]

    try:
        _openai = get_platform_client()
        resp = await _openai.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size=size,
            quality="standard",
            style="vivid",
        )
        image_url = resp.data[0].url
        return image_url, prompt
    except Exception as e:
        logger.error(f"DALL-E generation error: {e}")
        raise RuntimeError(f"Génération image échouée : {e}")


# ─── Network publishers ───────────────────────────────────────────────────────

async def _publish_instagram(store: Store, caption: str, image_url: str, post_type: str) -> dict:
    from utils.instagram_client import InstagramClient
    client = InstagramClient(store)
    if not client.is_configured:
        return {"ok": False, "error": "Instagram non configuré"}
    try:
        if post_type == "story":
            return await client.publish_story(image_url)
        else:
            return await client.publish_post(caption, image_url)
    except Exception as e:
        logger.error(f"Instagram publish error: {e}")
        return {"ok": False, "error": str(e)}


async def _publish_facebook(store: Store, caption: str, image_url: str | None, post_type: str) -> dict:
    from utils.facebook_client import FacebookClient
    client = FacebookClient(store)
    if not client.is_configured:
        return {"ok": False, "error": "Facebook non configuré"}
    try:
        return await client.publish_post(caption, image_url)
    except Exception as e:
        logger.error(f"Facebook publish error: {e}")
        return {"ok": False, "error": str(e)}


async def _publish_tiktok(store: Store, caption: str, image_url: str | None) -> dict:
    from utils.tiktok_client import TikTokClient
    client = TikTokClient(store)
    if not client.is_configured:
        return {"ok": False, "error": "TikTok non configuré"}
    if not image_url:
        return {"ok": False, "error": "Image requise pour TikTok"}
    try:
        return await client.publish_photo([image_url], caption)
    except Exception as e:
        logger.error(f"TikTok publish error: {e}")
        return {"ok": False, "error": str(e)}


async def _publish_to(store: Store, network: str, caption: str, image_url: str | None, post_type: str) -> dict:
    """Dispatch vers le bon publisher réseau."""
    if network == "instagram":
        return await _publish_instagram(store, caption, image_url or "", post_type)
    elif network == "facebook":
        return await _publish_facebook(store, caption, image_url, post_type)
    elif network == "tiktok":
        return await _publish_tiktok(store, caption, image_url)
    return {"ok": False, "error": f"Réseau {network} non supporté"}


# ─── Core publish pipeline ────────────────────────────────────────────────────

async def run_publish_pipeline(
    db: AsyncSession,
    store: Store,
    config: SocialPostConfig | None,
    topic: str,
    networks: list[str],
    post_type: str = "post",
    generate_image: bool = True,
    custom_caption: str | None = None,
    custom_image_url: str | None = None,
    product_id: int | None = None,
    source: str = "manual",
    extra_context: str = "",
) -> dict:
    """
    Pipeline complet :
    1. Génère caption (GPT-4o)
    2. Génère image (DALL-E 3) si demandé et pas d'image custom
    3. Publie sur chaque réseau
    4. Enregistre dans social_posts
    """
    results = []
    caption = custom_caption
    image_url = custom_image_url
    image_prompt = None

    # ── Étape 1 : Caption ─────────────────────────────────────────────────────
    if not caption:
        # Générer pour chaque réseau (légèrement différent)
        caption = await generate_caption(
            topic=topic,
            network=networks[0] if networks else "instagram",
            post_type=post_type,
            config=config,
            store_name=store.name or "Boutique",
            extra_context=extra_context,
        )

    # ── Étape 2 : Image DALL-E ────────────────────────────────────────────────
    dalle_error = None
    if generate_image and not image_url:
        try:
            image_url, image_prompt = await generate_image_dalle(topic, config)
        except Exception as e:
            dalle_error = str(e)
            logger.warning(f"DALL-E failed, continuing without image: {e}")

    # ── Étape 3 : Publication ─────────────────────────────────────────────────
    for network in networks:
        # Créer l'entrée DB d'abord (status=pending)
        post = SocialPost(
            store_id=store.id,
            network=network,
            post_type=post_type,
            status="pending",
            caption=caption,
            image_url=image_url,
            image_prompt=image_prompt,
            source=source,
            product_id=product_id,
        )
        db.add(post)
        await db.flush()

        # Publier
        result = await _publish_to(store, network, caption, image_url, post_type)

        # Mettre à jour le statut
        if result.get("ok"):
            post.status = "published"
            post.published_at = datetime.now(UTC)
            post.external_post_id = str(result.get("post_id") or result.get("story_id") or result.get("publish_id") or "")
        else:
            post.status = "failed"
            post.error = result.get("error", "unknown")

        results.append({
            "network": network,
            "ok": result.get("ok", False),
            "post_id": post.id,
            "external_id": post.external_post_id,
            "error": result.get("error"),
        })

    await db.commit()

    success = sum(1 for r in results if r["ok"])
    return {
        "ok": success > 0,
        "caption": caption,
        "image_url": image_url,
        "image_prompt": image_prompt,
        "dalle_error": dalle_error,
        "results": results,
        "published": success,
        "failed": len(results) - success,
    }


# ─── Next optimal post time ───────────────────────────────────────────────────

def get_next_post_time(config: SocialPostConfig) -> datetime | None:
    """
    Calcule le prochain créneau de publication optimal selon la config.
    Retourne None si auto_schedule est désactivé.
    """
    if not config or not config.auto_schedule:
        return None

    try:
        tz = ZoneInfo(config.timezone or "Africa/Tunis")
        now = datetime.now(tz)
        post_times = json.loads(config.post_times or '["09:00","12:00","18:00"]')
        post_days = json.loads(config.post_days or '[0,1,2,3,4,5,6]')  # 0=lundi

        # Chercher le prochain créneau disponible dans les 7 prochains jours
        for days_ahead in range(8):
            candidate_date = now.date() + timedelta(days=days_ahead)
            weekday = candidate_date.weekday()
            if weekday not in post_days:
                continue
            for time_str in sorted(post_times):
                h, m = map(int, time_str.split(":"))
                candidate = datetime.combine(
                    candidate_date,
                    datetime.min.time()
                ).replace(hour=h, minute=m, tzinfo=tz)
                if candidate > now + timedelta(minutes=5):
                    return candidate
    except Exception as e:
        logger.warning(f"get_next_post_time error: {e}")

    return None
