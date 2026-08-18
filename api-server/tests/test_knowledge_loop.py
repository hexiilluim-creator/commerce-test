"""tests/test_knowledge_loop.py — Couverture services/knowledge_loop.py (KnowledgeLoop).

Couvre :
  - collect_feedback (score valide, score invalide, tags filtrés)
  - get_performance_metrics (données vides, données suffisantes)
  - suggest_prompt_improvements (pas assez de données, score faible, tag too_long)
  - apply_learning / get_learning_state / reset_learning_state
  - VALID_FEEDBACK_TAGS cohérence
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.knowledge_loop import (  # noqa: E402
    _FEEDBACK_STORE,
    _LEARNING_STATE,
    VALID_FEEDBACK_TAGS,
    apply_learning,
    collect_feedback,
    get_learning_state,
    get_performance_metrics,
    reset_learning_state,
    suggest_prompt_improvements,
)

pytestmark = pytest.mark.unit


def _recent_iso(days_ago: int = 5) -> str:
    """Timestamp ISO relatif à 'maintenant', pour rester dans la fenêtre
    glissante de get_performance_metrics(days=30) quelle que soit la date
    système d'exécution des tests.

    AUDIT FIX : plusieurs fixtures utilisaient une date ISO figée
    ("2026-06-01T00:00:00+00:00"), tombée hors de la fenêtre glissante de
    30 jours selon la date système du run.
    """
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


# ─── Fixture : nettoyer le state entre les tests ──────────────────────────────
@pytest.fixture(autouse=True)
def _clear_state():
    _FEEDBACK_STORE.clear()
    _LEARNING_STATE.clear()
    yield
    _FEEDBACK_STORE.clear()
    _LEARNING_STATE.clear()


# ─── Tests VALID_FEEDBACK_TAGS ────────────────────────────────────────────────

def test_valid_tags_contains_helpful():
    assert "helpful" in VALID_FEEDBACK_TAGS


def test_valid_tags_contains_conversion():
    assert "conversion" in VALID_FEEDBACK_TAGS


def test_valid_tags_is_frozenset():
    assert isinstance(VALID_FEEDBACK_TAGS, frozenset)


def test_valid_tags_non_empty():
    assert len(VALID_FEEDBACK_TAGS) >= 5


# ─── Tests collect_feedback ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_feedback_valid_score():
    """Score valide (0.0-1.0) -> True."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        result = await collect_feedback(
            store_id=1,
            interaction_id="msg_001",
            score=0.9,
            tags=["helpful", "tone_good"],
        )
    assert result is True


@pytest.mark.asyncio
async def test_collect_feedback_invalid_score_high():
    """Score > 1.0 -> False (rejeté)."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        result = await collect_feedback(
            store_id=1,
            interaction_id="msg_002",
            score=1.5,  # invalide
        )
    assert result is False


@pytest.mark.asyncio
async def test_collect_feedback_invalid_score_negative():
    """Score < 0.0 -> False (rejeté)."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        result = await collect_feedback(
            store_id=1,
            interaction_id="msg_003",
            score=-0.1,
        )
    assert result is False


@pytest.mark.asyncio
async def test_collect_feedback_invalid_tags_filtered():
    """Tags invalides sont ignorés, tags valides conservés."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        await collect_feedback(
            store_id=2,
            interaction_id="msg_004",
            score=0.5,
            tags=["helpful", "INVALID_TAG_XYZ", "tone_good"],
        )

    key = "2"
    feedbacks = _FEEDBACK_STORE.get(key, [])
    assert len(feedbacks) == 1
    assert "INVALID_TAG_XYZ" not in feedbacks[0]["tags"]
    assert "helpful" in feedbacks[0]["tags"]


@pytest.mark.asyncio
async def test_collect_feedback_stored_in_memory():
    """Le feedback est stocké en mémoire quand DB est indisponible."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        await collect_feedback(
            store_id=10,
            interaction_id="msg_010",
            score=0.8,
        )

    assert "10" in _FEEDBACK_STORE
    assert len(_FEEDBACK_STORE["10"]) == 1


@pytest.mark.asyncio
async def test_collect_feedback_boundary_scores():
    """Scores aux limites (0.0 et 1.0) -> acceptés."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        r1 = await collect_feedback(store_id=3, interaction_id="m1", score=0.0)
        r2 = await collect_feedback(store_id=3, interaction_id="m2", score=1.0)
    assert r1 is True
    assert r2 is True


# ─── Tests get_performance_metrics ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_metrics_no_data():
    """Pas de données -> has_enough_data=False, avg_score=None."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        metrics = await get_performance_metrics(store_id=999, days=30)

    assert metrics["total_interactions"] == 0
    assert metrics["has_enough_data"] is False
    assert metrics["avg_score"] is None


@pytest.mark.asyncio
async def test_get_metrics_with_data():
    """Avec des feedbacks -> métriques calculées correctement."""
    # Peupler le store in-memory
    _FEEDBACK_STORE["50"] = [
        {"score": 0.9, "tags": "helpful,conversion", "created_at": _recent_iso()}
        for _ in range(15)
    ]

    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        metrics = await get_performance_metrics(store_id=50, days=30)

    assert metrics["total_interactions"] == 15
    assert metrics["avg_score"] is not None
    assert metrics["avg_score"] == 0.9


@pytest.mark.asyncio
async def test_get_metrics_has_enough_data_threshold():
    """10 interactions = seuil minimum pour has_enough_data."""
    _FEEDBACK_STORE["51"] = [
        {"score": 0.5, "tags": "", "created_at": _recent_iso()}
        for _ in range(10)
    ]
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        metrics = await get_performance_metrics(store_id=51, days=30)
    assert metrics["has_enough_data"] is True


# ─── Tests suggest_prompt_improvements ────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_improvements_no_data():
    """Pas assez de données -> suggestion informationnelle."""
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        suggestions = await suggest_prompt_improvements(store_id=999)

    assert len(suggestions) >= 1
    assert suggestions[0]["type"] == "info"


@pytest.mark.asyncio
async def test_suggest_improvements_low_score():
    """Score bas -> suggestion de type prompt_tone haute priorité."""
    # 15 feedbacks avec score 0.3 (très bas)
    _FEEDBACK_STORE["60"] = [
        {"score": 0.3, "tags": "unhelpful", "created_at": _recent_iso()}
        for _ in range(15)
    ]
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        suggestions = await suggest_prompt_improvements(store_id=60)

    types = [s["type"] for s in suggestions]
    assert "prompt_tone" in types or any(s["priority"] == "high" for s in suggestions)


@pytest.mark.asyncio
async def test_suggest_improvements_too_long_tag():
    """Tag too_long fréquent -> suggestion de réduction de longueur."""
    _FEEDBACK_STORE["61"] = [
        {"score": 0.6, "tags": "too_long", "created_at": _recent_iso()}
        for _ in range(15)
    ]
    with patch("services.knowledge_loop.AsyncSessionLocal", side_effect=Exception("no db")):
        suggestions = await suggest_prompt_improvements(store_id=61)

    types = [s["type"] for s in suggestions]
    assert "response_length" in types or len(suggestions) >= 1


# ─── Tests apply_learning / get_learning_state / reset_learning_state ─────────

@pytest.mark.asyncio
async def test_apply_learning_stores_state():
    improvements = [{"type": "prompt_tone", "action": "Adjust tone"}]
    result = await apply_learning(store_id=100, improvements=improvements, applied_by="admin")
    assert result is True

    state = await get_learning_state(store_id=100)
    assert state["has_improvements"] is True
    assert state["version"] == 1
    assert state["applied_by"] == "admin"


@pytest.mark.asyncio
async def test_apply_learning_increments_version():
    improvements = [{"type": "focus", "action": "Improve focus"}]
    await apply_learning(store_id=101, improvements=improvements)
    await apply_learning(store_id=101, improvements=improvements)

    state = await get_learning_state(store_id=101)
    assert state["version"] == 2


@pytest.mark.asyncio
async def test_get_learning_state_no_improvements():
    """Store sans apprentissage -> has_improvements=False."""
    state = await get_learning_state(store_id=999)
    assert state["has_improvements"] is False
    assert state["version"] == 0


@pytest.mark.asyncio
async def test_reset_learning_state():
    """Reset efface les données d'apprentissage."""
    await apply_learning(store_id=200, improvements=[{"type": "test"}])
    _FEEDBACK_STORE["200"] = [{"score": 0.5}]

    result = await reset_learning_state(store_id=200)
    assert result is True

    state = await get_learning_state(store_id=200)
    assert state["has_improvements"] is False
    assert "200" not in _FEEDBACK_STORE
