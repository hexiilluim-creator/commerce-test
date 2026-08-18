"""api/v1/visual_builder.py — Plan E1 routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id, require_feature, require_role
from models.database import get_db
from models.visual_builder import (
    VisualBuild,
    VisualBuildHistory,
    VisualBuildReview,
    VisualBuildStatus,
)
from services.visual_builder_service import (
    enhance_photos,
)
from services.visual_builder_service import (
    generate_description as svc_generate_description,
)
from services.visual_builder_service import (
    generate_seo as svc_generate_seo,
)
from services.visual_builder_service import (
    list_history as svc_list_history,
)
from services.visual_builder_service import (
    publish as svc_publish,
)
from services.visual_builder_service import (
    review_build as svc_review_build,
)
from services.visual_builder_service import (
    submit_for_review as svc_submit_review,
)
from services.visual_builder_service import (
    translate_content as svc_translate,
)

router = APIRouter(prefix="/visual-builder", tags=["Plan E — Visual Builder"], dependencies=[require_feature("visual_builder")])


# ─── Schemas ────────────────────────────────────────────────────────────────

class GenerateDescriptionIn(BaseModel):
    product_name: str = Field(..., min_length=1, max_length=200)
    category: str | None = Field(None, max_length=80)
    tone: str = Field("premium", max_length=40)
    product_id: int | None = None


class EnhancePhotosIn(BaseModel):
    image_urls: list[str] = Field(..., min_length=1, max_length=20)
    backgrounds: list[str] | None = None


class SeoIn(BaseModel):
    target_locale: str = Field("fr", max_length=8)
    keywords: list[str] = Field(default_factory=list, max_length=20)


class TranslateIn(BaseModel):
    target_locales: list[str] = Field(..., min_length=1, max_length=20)
    glossary: dict[str, str] = Field(default_factory=dict)


class ReviewIn(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|changes_requested)$")
    comments: str | None = Field(None, max_length=4000)


class BuildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    product_id: int | None
    locale_default: str
    description_short: str | None
    description_long: str | None
    bullets: list[str] | None
    seo_title: str | None
    seo_meta: str | None
    seo_keywords: list[str] | None
    seo_og: dict | None
    seo_score: int | None
    translations: dict | None
    status: str
    model_version: str | None
    created_at: datetime | None
    updated_at: datetime | None


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    build_id: int
    actor_id: int | None
    action: str
    before: dict | None
    after: dict | None
    model_version: str | None
    notes: str | None
    created_at: datetime | None


# ─── helpers ────────────────────────────────────────────────────────────────

async def _load_build(session: AsyncSession, store_id: int, build_id: int) -> VisualBuild:
    res = await session.execute(
        select(VisualBuild).where(
            VisualBuild.id == build_id, VisualBuild.store_id == store_id
        )
    )
    build = res.scalar_one_or_none()
    if build is None:
        raise HTTPException(status_code=404, detail="Visual build introuvable")
    return build


# ─── Routes ─────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=BuildOut, dependencies=[require_role("manager")])
async def generate_description(
    payload: GenerateDescriptionIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await svc_generate_description(
        session,
        store_id=store_id,
        product_name=payload.product_name,
        category=payload.category,
        tone=payload.tone,
        actor_id=getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id"),
    )
    if payload.product_id is not None:
        build.product_id = payload.product_id
        await session.flush()
    await session.commit()
    await session.refresh(build)
    return BuildOut.model_validate(build)


@router.post("/{build_id}/photos", dependencies=[require_role("manager")])
async def add_photos(
    build_id: int,
    payload: EnhancePhotosIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    assets = await enhance_photos(
        session,
        build_id=build.id,
        store_id=store_id,
        image_urls=payload.image_urls,
        backgrounds=payload.backgrounds,
        actor_id=getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id"),
    )
    await session.commit()
    return {"build_id": build.id, "assets": [{"id": a.id, "url": a.url, "alt": a.alt_text} for a in assets]}


@router.put("/{build_id}/seo", response_model=BuildOut, dependencies=[require_role("manager")])
async def set_seo(
    build_id: int,
    payload: SeoIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    await svc_generate_seo(
        session, build=build, target_locale=payload.target_locale, keywords=payload.keywords,
        actor_id=getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id"),
    )
    await session.commit()
    await session.refresh(build)
    return BuildOut.model_validate(build)


@router.put("/{build_id}/translations", response_model=BuildOut, dependencies=[require_role("manager")])
async def set_translations(
    build_id: int,
    payload: TranslateIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    await svc_translate(
        session, build=build, target_locales=payload.target_locales, glossary=payload.glossary,
        actor_id=getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id"),
    )
    await session.commit()
    await session.refresh(build)
    return BuildOut.model_validate(build)


@router.post("/{build_id}/submit", response_model=BuildOut, dependencies=[require_role("manager")])
async def submit_for_review(
    build_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    await svc_submit_review(session, build=build, actor_id=None)
    await session.commit()
    await session.refresh(build)
    return BuildOut.model_validate(build)


@router.post("/{build_id}/review", dependencies=[require_role("admin")])
async def review(
    build_id: int,
    payload: ReviewIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    reviewer_id = getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id") or 0
    await svc_review_build(session, build=build, reviewer_id=int(reviewer_id),
                            decision=payload.decision, comments=payload.comments)
    await session.commit()
    return {"build_id": build.id, "status": build.status.value}


@router.post("/{build_id}/publish", response_model=BuildOut, dependencies=[require_role("admin")])
async def publish_build(
    build_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    build = await _load_build(session, store_id, build_id)
    await svc_publish(session, build=build, actor_id=None)
    await session.commit()
    await session.refresh(build)
    return BuildOut.model_validate(build)


@router.get("/{build_id}/history", response_model=list[HistoryOut])
async def history(
    build_id: int,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    rows = await svc_list_history(session, store_id=store_id, build_id=build_id, limit=limit)
    return [HistoryOut.model_validate(r) for r in rows]


@router.get("/", response_model=list[BuildOut])
async def list_builds(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    stmt = select(VisualBuild).where(VisualBuild.store_id == store_id)
    if status:
        stmt = stmt.where(VisualBuild.status == status)
    stmt = stmt.order_by(VisualBuild.updated_at.desc()).limit(limit)
    res = await session.execute(stmt)
    return [BuildOut.model_validate(b) for b in res.scalars().all()]
