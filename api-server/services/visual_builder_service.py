"""
services/visual_builder_service.py — Plan E1 business logic.

V28 P1-fix : les 4 fonctions génératives (description, alt-text, SEO,
traduction) sont désormais routées via `services.llm_gateway.chat()`
(DeepSeek primaire, fallback OpenAI, circuit breaker, budget, quota —
déjà utilisé ailleurs dans l'app, voir auto_parts_agent.py / vin_decoder.py).
Elles ne passent plus par `llm_stub` : un client payant ne reçoit plus de
texte lorem-ipsum déterministe en pensant utiliser un vrai générateur IA.

`seo_score` reste sur `llm_stub` : c'est un scoring heuristique local
(longueurs de titre/meta, couverture de mots-clés), pas une simulation
d'appel IA — aucune raison de le faire transiter par un LLM.

En cas d'échec du gateway (budget dépassé, tous providers down, JSON
invalide) : on lève une HTTPException(502) explicite. Pas de repli
silencieux vers du contenu factice sur une feature facturée.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.visual_builder import (
    VisualBuild,
    VisualBuildAsset,
    VisualBuildHistory,
    VisualBuildReview,
    VisualBuildStatus,
)
from services import llm_gateway
from services.llm_gateway import AllProvidersFailedError, BudgetExceededError
from services.llm_stub import seo_score  # heuristique locale, pas un appel IA

logger = logging.getLogger("visual_builder_service")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def _chat_json(
    *,
    system: str,
    user: str,
    store_id: int | None,
    agent_name: str,
    max_tokens: int = 700,
    temperature: float = 0.7,
) -> tuple[Any, str]:
    """Appelle llm_gateway.chat(), parse la réponse JSON, renvoie (data, model_version).

    Échec (budget, tous providers down, JSON invalide) -> HTTPException(502).
    Jamais de repli silencieux vers un texte factice pour une feature facturée.
    """
    try:
        result = await llm_gateway.chat(
            messages=[{"role": "user", "content": user}],
            system=system,
            tenant_id=store_id,
            agent_name=agent_name,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except (BudgetExceededError, AllProvidersFailedError) as exc:
        logger.error("visual_builder llm_gateway failed agent=%s error=%s", agent_name, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Génération IA indisponible ({agent_name}): {exc}",
        ) from exc

    raw = _strip_fences(result.content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("visual_builder JSON invalide agent=%s content=%r", agent_name, raw[:300])
        raise HTTPException(
            status_code=502,
            detail=f"Réponse IA invalide ({agent_name})",
        ) from exc

    model_version = f"{result.provider}:{result.model}"
    return data, model_version


# ─────────────────────────────── Description ────────────────────────────────

_DESC_SYSTEM = (
    "Tu es un rédacteur e-commerce professionnel pour le marché tunisien/maghrébin. "
    "Réponds UNIQUEMENT avec un objet JSON valide, sans texte ni markdown autour, au format : "
    '{"short": "description courte (<=140 caractères)", '
    '"long": "description longue (<=900 caractères)", '
    '"bullets": ["point 1", "point 2", "point 3", "point 4"]}'
)


async def generate_description(
    session: AsyncSession,
    *,
    store_id: int,
    product_name: str,
    category: str | None = None,
    tone: str = "premium",
    actor_id: int | None = None,
) -> VisualBuild:
    user_prompt = (
        f"Produit : {product_name}\n"
        f"Catégorie : {category or 'générale'}\n"
        f"Ton souhaité : {tone}"
    )
    data, model_version = await _chat_json(
        system=_DESC_SYSTEM,
        user=user_prompt,
        store_id=store_id,
        agent_name="visual_builder_description",
        max_tokens=700,
    )
    short = str(data.get("short", ""))[:140]
    long_text = str(data.get("long", ""))[:900]
    bullets = [str(b) for b in (data.get("bullets") or [])][:4]

    build = VisualBuild(
        store_id=store_id,
        locale_default="fr",
        description_short=short,
        description_long=long_text,
        bullets=bullets,
        status=VisualBuildStatus.DRAFT,
        model_version=model_version,
        created_by=actor_id,
        translations={},
        glossary={},
    )
    session.add(build)
    await session.flush()
    await _record_history(session, store_id, build.id, actor_id, "generate_description",
                          before=None, after={"short": short, "long": long_text, "bullets": bullets},
                          model_version=model_version)
    return build


# ─────────────────────────────── Photos (alt-text via LLM) ──────────────────

_ALT_TEXT_SYSTEM = (
    "Tu es un expert en accessibilité web et SEO e-commerce. On te donne une liste "
    "ordonnée d'images produit (URL + fond éventuel). Génère un texte alternatif (alt) "
    "concis et descriptif en français pour chacune (<=110 caractères). "
    "Réponds UNIQUEMENT avec un tableau JSON de chaînes, dans le même ordre, une entrée par image."
)


async def enhance_photos(
    session: AsyncSession,
    *,
    build_id: int,
    store_id: int,
    image_urls: list[str],
    backgrounds: list[str] | None = None,
    actor_id: int | None = None,
) -> list[VisualBuildAsset]:
    if not image_urls:
        return []

    lines = [
        f"{idx + 1}. url={url} fond={(backgrounds[idx] if backgrounds and idx < len(backgrounds) else None) or 'inchangé'}"
        for idx, url in enumerate(image_urls)
    ]
    user_prompt = "Images :\n" + "\n".join(lines)

    data, model_version = await _chat_json(
        system=_ALT_TEXT_SYSTEM,
        user=user_prompt,
        store_id=store_id,
        agent_name="visual_builder_alt_text",
        max_tokens=60 * len(image_urls) + 100,
    )
    if not isinstance(data, list) or len(data) != len(image_urls):
        logger.warning(
            "visual_builder alt_text: réponse IA de longueur inattendue (%s attendu, reçu=%r)",
            len(image_urls), data,
        )
    alts = [str(a) for a in data] if isinstance(data, list) else []

    out: list[VisualBuildAsset] = []
    for idx, url in enumerate(image_urls):
        alt = alts[idx][:110] if idx < len(alts) and alts[idx] else f"Photo produit {idx + 1}"
        asset = VisualBuildAsset(
            build_id=build_id,
            kind="enhanced" if idx > 0 else "photo",
            url=url,
            alt_text=alt,
            order=idx,
            is_primary=(idx == 0),
            ai_metadata={
                "background": backgrounds[idx] if backgrounds and idx < len(backgrounds) else None,
                "model": model_version,
                "processed_at": datetime.now(UTC).isoformat(),
            },
        )
        session.add(asset)
        out.append(asset)
    await session.flush()
    await _record_history(session, store_id, build_id, actor_id, "enhance_photos",
                          before=None, after={"assets": [a.url for a in out]},
                          model_version=model_version)
    return out


# ─────────────────────────────── SEO ───────────────────────────────────────

_SEO_SYSTEM = (
    "Tu es un expert SEO e-commerce francophone. Réponds UNIQUEMENT avec un objet JSON "
    'valide au format {"title": "titre SEO (<=70 caractères)", '
    '"meta": "meta description (<=170 caractères)"}.'
)


async def generate_seo(
    session: AsyncSession,
    *,
    build: VisualBuild,
    target_locale: str = "fr",
    keywords: list[str] | None = None,
    actor_id: int | None = None,
) -> VisualBuild:
    keywords = keywords or []
    user_prompt = (
        f"Description produit : {build.description_short or ''}\n"
        f"Mots-clés à intégrer si pertinent : {', '.join(keywords) or 'aucun'}\n"
        f"Locale cible : {target_locale}"
    )
    data, model_version = await _chat_json(
        system=_SEO_SYSTEM,
        user=user_prompt,
        store_id=build.store_id,
        agent_name="visual_builder_seo",
        max_tokens=200,
    )
    title = str(data.get("title", ""))[:70]
    meta = str(data.get("meta", ""))[:170]
    og = {"title": title, "description": meta, "image": None}
    score = seo_score(title, meta, keywords)

    build.seo_title = title
    build.seo_meta = meta
    build.seo_keywords = keywords
    build.seo_og = og
    build.seo_score = score
    build.model_version = model_version
    await session.flush()
    await _record_history(session, build.store_id, build.id, actor_id, "generate_seo",
                          before=None, after={"title": title, "meta": meta, "score": score,
                                              "keywords": keywords},
                          model_version=model_version)
    return build


# ─────────────────────────────── Traductions ───────────────────────────────

_TRANSLATE_SYSTEM = (
    "Tu es un traducteur professionnel e-commerce. Traduis fidèlement le contenu fourni "
    "vers la langue/locale cible. Si un glossaire est fourni, utilise ces termes exacts, "
    "verbatim, partout où ils s'appliquent. Réponds UNIQUEMENT avec un objet JSON valide au format : "
    '{"description_short": "...", "description_long": "...", "seo_title": "...", '
    '"seo_meta": "...", "bullets": ["...", "..."]}. Conserve le même nombre de bullets '
    "que dans le texte source, dans le même ordre."
)


async def translate_content(
    session: AsyncSession,
    *,
    build: VisualBuild,
    target_locales: list[str],
    glossary: dict | None = None,
    actor_id: int | None = None,
) -> VisualBuild:
    glossary = glossary or {}
    translations = dict(build.translations or {})
    last_model_version: str | None = None

    source = {
        "description_short": build.description_short or "",
        "description_long": build.description_long or "",
        "seo_title": build.seo_title or "",
        "seo_meta": build.seo_meta or "",
        "bullets": list(build.bullets or []),
    }

    for locale in target_locales:
        user_prompt = (
            f"Locale cible : {locale}\n"
            f"Glossaire (termes à garder verbatim) : {json.dumps(glossary, ensure_ascii=False)}\n"
            f"Contenu source (JSON) : {json.dumps(source, ensure_ascii=False)}"
        )
        data, model_version = await _chat_json(
            system=_TRANSLATE_SYSTEM,
            user=user_prompt,
            store_id=build.store_id,
            agent_name="visual_builder_translate",
            max_tokens=1200,
        )
        last_model_version = model_version
        existing = translations.get(locale, {})
        existing["description_short"] = str(data.get("description_short", ""))
        existing["description_long"] = str(data.get("description_long", ""))
        existing["seo_title"] = str(data.get("seo_title", ""))
        existing["seo_meta"] = str(data.get("seo_meta", ""))
        existing["bullets"] = [str(b) for b in (data.get("bullets") or [])]
        translations[locale] = existing

    build.translations = translations
    build.glossary = glossary
    if last_model_version:
        build.model_version = last_model_version
    await session.flush()
    await _record_history(session, build.store_id, build.id, actor_id, "translate_content",
                          before=None, after={"locales": target_locales},
                          model_version=last_model_version)
    return build


# ─────────────────────────────── Validation humaine ────────────────────────

async def submit_for_review(
    session: AsyncSession, *, build: VisualBuild, actor_id: int | None
) -> VisualBuild:
    build.status = VisualBuildStatus.PENDING_REVIEW
    await session.flush()
    await _record_history(session, build.store_id, build.id, actor_id,
                          "submit_for_review", None, {"status": build.status.value})
    return build


async def review_build(
    session: AsyncSession,
    *,
    build: VisualBuild,
    reviewer_id: int,
    decision: str,
    comments: str | None,
) -> VisualBuild:
    if decision not in {"approve", "reject", "changes_requested"}:
        raise ValueError(f"Invalid decision: {decision}")
    new_status = {
        "approve": VisualBuildStatus.APPROVED,
        "reject": VisualBuildStatus.REJECTED,
        "changes_requested": VisualBuildStatus.CHANGES_REQUESTED,
    }[decision]
    preview_before = {
        "status": build.status.value,
        "description_short": build.description_short,
        "seo_title": build.seo_title,
    }
    build.status = new_status
    review = VisualBuildReview(
        build_id=build.id,
        reviewer_id=reviewer_id,
        decision=decision,
        comments=comments,
        diff={"before": preview_before, "after": {"status": new_status.value}},
    )
    session.add(review)
    await session.flush()
    await _record_history(session, build.store_id, build.id, reviewer_id,
                          f"review:{decision}", preview_before, {"status": new_status.value})
    return build


async def publish(
    session: AsyncSession, *, build: VisualBuild, actor_id: int | None
) -> VisualBuild:
    if build.status not in {VisualBuildStatus.APPROVED, VisualBuildStatus.PENDING_REVIEW}:
        # Allow direct publish after approval only.
        raise HTTPException(status_code=409, detail="Build must be approved before publish")
    build.status = VisualBuildStatus.PUBLISHED
    await session.flush()
    await _record_history(session, build.store_id, build.id, actor_id,
                          "publish", None, {"status": build.status.value})
    return build


# ─────────────────────────────── Historique ────────────────────────────────

async def list_history(
    session: AsyncSession, *, store_id: int, build_id: int, limit: int = 100
) -> list[VisualBuildHistory]:
    res = await session.execute(
        select(VisualBuildHistory)
        .where(VisualBuildHistory.store_id == store_id,
               VisualBuildHistory.build_id == build_id)
        .order_by(VisualBuildHistory.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def _record_history(
    session: AsyncSession,
    store_id: int,
    build_id: int,
    actor_id: int | None,
    action: str,
    before: dict | None,
    after: dict | None,
    model_version: str | None = None,
) -> None:
    row = VisualBuildHistory(
        store_id=store_id,
        build_id=build_id,
        actor_id=actor_id,
        action=action,
        before=before or {},
        after=after or {},
        model_version=model_version,
    )
    session.add(row)
    await session.flush()
