"""tests/test_visual_builder_service.py — Tests pour services/visual_builder_service.py (Plan E1).

BUG#10 FIX: ce module (262 lignes) était à 0% de couverture de tests.
Utilise une DB SQLite in-memory locale et indépendante des fixtures d'intégration.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.database import Base
from models.visual_builder import VisualBuildStatus
from services.llm_gateway import ChatCompletion
from services.visual_builder_service import (
    enhance_photos,
    generate_description,
    generate_seo,
    list_history,
    publish,
    review_build,
    submit_for_review,
    translate_content,
)


async def _fake_llm_chat(*, messages, system=None, agent_name="chat", **kwargs):
    """Réponse JSON déterministe par agent_name — remplace le vrai appel réseau
    pour que ces tests restent offline (pattern identique à
    tests/test_auto_parts_services.py, qui mocke services.llm_gateway.chat)."""
    user_content = messages[0]["content"] if messages else ""
    if agent_name == "visual_builder_description":
        content = json.dumps({
            "short": "Robe légère et élégante pour l'été.",
            "long": "Une description longue et détaillée du produit, pensée pour convertir.",
            "bullets": ["Premium", "Durable", "Léger", "Élégant"],
        })
    elif agent_name == "visual_builder_alt_text":
        n = user_content.count("url=")
        content = json.dumps([f"Photo produit {i + 1}" for i in range(n)])
    elif agent_name == "visual_builder_seo":
        content = json.dumps({
            "title": "Titre SEO optimisé pour le produit",
            "meta": "Meta description optimisée pour le référencement du produit, claire et engageante.",
        })
    elif agent_name == "visual_builder_translate":
        content = json.dumps({
            "description_short": "Short translated.",
            "description_long": "Long translated.",
            "seo_title": "Translated title",
            "seo_meta": "Translated meta",
            "bullets": ["Premium", "Durable", "Léger", "Élégant"],
        })
    else:
        content = "{}"
    return ChatCompletion(content=content, model="mock-model", provider="mock",
                           input_tokens=10, output_tokens=10)


@pytest.fixture(autouse=True)
def mock_llm_gateway():
    with patch("services.llm_gateway.chat", new=AsyncMock(side_effect=_fake_llm_chat)):
        yield


@pytest_asyncio.fixture
async def vb_session():
    """Session SQLite in-memory isolée, dédiée à ce fichier de tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─── generate_description ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_description_happy_path(vb_session):
    build = await generate_description(
        vb_session,
        store_id=1,
        product_name="Robe d'été",
        category="mode",
        tone="premium",
        actor_id=10,
    )
    assert build.id is not None
    assert build.store_id == 1
    assert build.status == VisualBuildStatus.DRAFT
    assert build.description_short
    assert build.description_long
    assert isinstance(build.bullets, list)


@pytest.mark.asyncio
async def test_generate_description_edge_case_empty_category(vb_session):
    """category=None doit fonctionner sans crash (fallback 'general')."""
    build = await generate_description(
        vb_session, store_id=1, product_name="Produit X", category=None,
    )
    assert build.description_short  # non-empty even with no category


@pytest.mark.asyncio
async def test_generate_description_invalid_input_empty_product_name(vb_session):
    """Nom de produit vide — ne doit pas lever d'exception (best-effort generation)."""
    build = await generate_description(vb_session, store_id=1, product_name="")
    assert build.id is not None  # still creates a build, even if content is weak


# ─── enhance_photos ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enhance_photos_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Sac")
    assets = await enhance_photos(
        vb_session,
        build_id=build.id,
        store_id=1,
        image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
    )
    assert len(assets) == 2
    assert assets[0].is_primary is True
    assert assets[1].is_primary is False


@pytest.mark.asyncio
async def test_enhance_photos_edge_case_empty_urls(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Sac")
    assets = await enhance_photos(vb_session, build_id=build.id, store_id=1, image_urls=[])
    assert assets == []


# ─── generate_seo ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_seo_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Montre")
    updated = await generate_seo(vb_session, build=build, keywords=["montre", "luxe"])
    assert updated.seo_title
    assert updated.seo_meta
    assert updated.seo_score is not None
    assert updated.seo_keywords == ["montre", "luxe"]


@pytest.mark.asyncio
async def test_generate_seo_edge_case_no_keywords(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Montre")
    updated = await generate_seo(vb_session, build=build, keywords=None)
    assert updated.seo_keywords == []


# ─── translate_content ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_translate_content_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Chaussures")
    updated = await translate_content(vb_session, build=build, target_locales=["en", "ar"])
    assert "en" in updated.translations
    assert "ar" in updated.translations


@pytest.mark.asyncio
async def test_translate_content_edge_case_empty_locales(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Chaussures")
    updated = await translate_content(vb_session, build=build, target_locales=[])
    assert updated.translations == {}


# ─── submit_for_review / review_build ───────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_for_review_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Veste")
    updated = await submit_for_review(vb_session, build=build, actor_id=5)
    assert updated.status == VisualBuildStatus.PENDING_REVIEW


@pytest.mark.asyncio
async def test_review_build_happy_path_approve(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Veste")
    await submit_for_review(vb_session, build=build, actor_id=5)
    updated = await review_build(
        vb_session, build=build, reviewer_id=99, decision="approve", comments="OK"
    )
    assert updated.status == VisualBuildStatus.APPROVED


@pytest.mark.asyncio
async def test_review_build_invalid_input_raises_valueerror(vb_session):
    """Décision invalide doit lever ValueError, pas planter silencieusement."""
    build = await generate_description(vb_session, store_id=1, product_name="Veste")
    with pytest.raises(ValueError):
        await review_build(
            vb_session, build=build, reviewer_id=99, decision="invalid_decision", comments=None
        )


# ─── publish ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Pull")
    await submit_for_review(vb_session, build=build, actor_id=5)
    await review_build(vb_session, build=build, reviewer_id=99, decision="approve", comments=None)
    updated = await publish(vb_session, build=build, actor_id=5)
    assert updated.status == VisualBuildStatus.PUBLISHED


@pytest.mark.asyncio
async def test_publish_invalid_input_unapproved_raises_409(vb_session):
    """Publier un build non approuvé doit lever HTTPException 409."""
    from fastapi import HTTPException
    build = await generate_description(vb_session, store_id=1, product_name="Pull")
    with pytest.raises(HTTPException) as exc_info:
        await publish(vb_session, build=build, actor_id=5)
    assert exc_info.value.status_code == 409


# ─── list_history ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_history_happy_path(vb_session):
    build = await generate_description(vb_session, store_id=1, product_name="Sac")
    history = await list_history(vb_session, store_id=1, build_id=build.id)
    assert len(history) >= 1
    assert history[0].action == "generate_description"


@pytest.mark.asyncio
async def test_list_history_edge_case_unknown_build(vb_session):
    """Build_id inexistant → liste vide, pas d'exception."""
    history = await list_history(vb_session, store_id=1, build_id=999999)
    assert history == []


# ─── DB error simulation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_description_db_error_propagates():
    """Si la session DB lève une SQLAlchemyError, elle doit se propager
    (pas d'avalage silencieux de l'erreur)."""
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock(side_effect=SQLAlchemyError("connection lost"))

    with pytest.raises(SQLAlchemyError):
        await generate_description(mock_session, store_id=1, product_name="Test")
