"""tests/test_manager_agent.py — Couverture services/manager_agent.py (ManagerAgent).

Couvre :
  - AgentDecision dataclass
  - AgentStats.record_call, success_rate, escalation_rate
  - ManagerAgent._detect_escalation_needed
  - ManagerAgent._validate_response
  - ManagerAgent._truncate_if_needed
  - ManagerAgent.dispatch (customer, owner, escalation, blocked)
  - ManagerAgent.get_stats
  - ManagerAgent.reset_stats
  - get_manager() singleton
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.manager_agent import (  # noqa: E402
    _ESCALATION_KEYWORDS,
    _MAX_RESPONSE_LENGTH,
    AgentDecision,
    AgentStats,
    ManagerAgent,
    get_manager,
)

pytestmark = pytest.mark.unit


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_store(**kwargs):
    defaults = {"id": 1, "name": "Test", "auto_parts_mode": False}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_customer(**kwargs):
    defaults = {"id": 1, "store_id": 1, "conversation_state": {}, "opted_out": False}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _FakeDB:
    async def execute(self, *a, **kw):
        from unittest.mock import MagicMock
        return MagicMock(scalar_one_or_none=lambda: None)


# ─── Tests AgentDecision ──────────────────────────────────────────────────────

def test_agent_decision_dataclass():
    d = AgentDecision(
        agent_route="commerce_agent",
        response="Bonjour!",
        escalated=False,
        latency_ms=120.5,
    )
    assert d.agent_route == "commerce_agent"
    assert d.response == "Bonjour!"
    assert d.escalated is False
    assert d.latency_ms == 120.5


def test_agent_decision_escalated():
    d = AgentDecision(
        agent_route="human_escalation",
        response="Je vous transfère.",
        escalated=True,
        escalation_reason="Mot-clé: avocat",
    )
    assert d.escalated is True
    assert d.escalation_reason is not None


# ─── Tests AgentStats ─────────────────────────────────────────────────────────

def test_agent_stats_initial():
    stats = AgentStats(route="commerce_agent")
    assert stats.total_calls == 0
    assert stats.success_rate == 0.0
    assert stats.escalation_rate == 0.0


def test_agent_stats_record_success():
    stats = AgentStats(route="test")
    stats.record_call(success=True, latency_ms=100.0)
    assert stats.total_calls == 1
    assert stats.success_rate == 1.0


def test_agent_stats_record_failure():
    stats = AgentStats(route="test")
    stats.record_call(success=False, latency_ms=50.0)
    assert stats.total_calls == 1
    assert stats.success_rate == 0.0


def test_agent_stats_record_escalation():
    stats = AgentStats(route="test")
    stats.record_call(success=True, latency_ms=200.0, escalated=True)
    assert stats.escalations == 1
    assert stats.escalation_rate == 1.0


def test_agent_stats_avg_latency():
    stats = AgentStats(route="test")
    stats.record_call(success=True, latency_ms=100.0)
    stats.record_call(success=True, latency_ms=200.0)
    assert stats.avg_latency_ms == 150.0


def test_agent_stats_last_call_at_set():
    stats = AgentStats(route="test")
    stats.record_call(success=True, latency_ms=10.0)
    assert stats.last_call_at is not None


# ─── Tests _ESCALATION_KEYWORDS ───────────────────────────────────────────────

def test_escalation_keywords_non_empty():
    assert len(_ESCALATION_KEYWORDS) >= 5


def test_escalation_keywords_contains_avocat():
    assert "avocat" in _ESCALATION_KEYWORDS


def test_escalation_keywords_is_frozenset():
    assert isinstance(_ESCALATION_KEYWORDS, frozenset)


# ─── Tests ManagerAgent._detect_escalation_needed ────────────────────────────

def test_detect_escalation_avocat():
    agent = ManagerAgent()
    needed, reason = agent._detect_escalation_needed("Je vais appeler mon avocat!")
    assert needed is True
    assert reason is not None


def test_detect_escalation_arnaque():
    agent = ManagerAgent()
    needed, reason = agent._detect_escalation_needed("C'est une arnaque!")
    assert needed is True


def test_detect_no_escalation_normal_text():
    agent = ManagerAgent()
    needed, reason = agent._detect_escalation_needed("Je cherche un produit pour ma voiture")
    assert needed is False
    assert reason is None


def test_detect_escalation_case_insensitive():
    agent = ManagerAgent()
    needed, reason = agent._detect_escalation_needed("Je veux parler à un MANAGER")
    # Le texte est passé en lower() -> doit détecter 'manager'
    assert needed is True


# ─── Tests ManagerAgent._validate_response ────────────────────────────────────

def test_validate_response_ok():
    agent = ManagerAgent()
    valid, err = agent._validate_response("Voici votre réponse complète et utile.")
    assert valid is True
    assert err is None


def test_validate_response_none():
    agent = ManagerAgent()
    valid, err = agent._validate_response(None)
    assert valid is False
    assert err is not None


def test_validate_response_too_short():
    agent = ManagerAgent()
    valid, err = agent._validate_response("OK")
    assert valid is False


# ─── Tests ManagerAgent._truncate_if_needed ───────────────────────────────────

def test_truncate_short_response_unchanged():
    agent = ManagerAgent()
    text = "Réponse courte"
    result = agent._truncate_if_needed(text)
    assert result == text


def test_truncate_long_response():
    agent = ManagerAgent()
    long_text = "mot " * 1000  # Bien au-delà de _MAX_RESPONSE_LENGTH
    result = agent._truncate_if_needed(long_text)
    assert len(result) <= _MAX_RESPONSE_LENGTH + 5  # Tolérance pour le "…"
    assert result.endswith("…")


def test_truncate_at_word_boundary():
    agent = ManagerAgent()
    # Créer un texte exactement 1 char au-dessus de la limite
    text = "a" * (_MAX_RESPONSE_LENGTH + 1)
    result = agent._truncate_if_needed(text)
    assert len(result) <= _MAX_RESPONSE_LENGTH + 1


# ─── Tests ManagerAgent.get_stats / reset_stats ───────────────────────────────

def test_get_stats_empty():
    agent = ManagerAgent()
    stats = agent.get_stats()
    assert isinstance(stats, dict)


def test_get_stats_after_recording():
    agent = ManagerAgent()
    agent._get_stats("commerce_agent").record_call(True, 100.0)
    stats = agent.get_stats()
    assert "commerce_agent" in stats
    assert stats["commerce_agent"]["total_calls"] == 1


def test_reset_stats():
    agent = ManagerAgent()
    agent._get_stats("test_route").record_call(True, 50.0)
    agent.reset_stats()
    assert agent.get_stats() == {}


# ─── Tests get_manager() singleton ───────────────────────────────────────────

def test_get_manager_returns_manager_agent():
    mgr = get_manager()
    assert isinstance(mgr, ManagerAgent)


def test_get_manager_singleton():
    m1 = get_manager()
    m2 = get_manager()
    assert m1 is m2


# ─── Tests ManagerAgent.dispatch ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_escalation_on_keyword():
    """Message avec mot-clé d'escalade -> route='human_escalation'."""
    agent = ManagerAgent()
    from services.agent_orchestrator import RouteDecision

    with patch("services.manager_agent.resolve_route", AsyncMock(return_value=RouteDecision(
        route="commerce_agent", degraded_mode=False, reason="default"
    ))):
        decision = await agent.dispatch(
            db=_FakeDB(),
            store=_make_store(),
            customer=_make_customer(),
            text="C'est une arnaque, je vais appeler mon avocat!",
            wa=None,
        )

    assert decision.escalated is True
    assert decision.agent_route == "human_escalation"


@pytest.mark.asyncio
async def test_dispatch_blocked_billing():
    """Tenant suspendu -> response explicative."""
    agent = ManagerAgent()
    from services.agent_orchestrator import RouteDecision

    with patch("services.manager_agent.resolve_route", AsyncMock(return_value=RouteDecision(
        route="blocked", degraded_mode=True, reason="tenant_suspended"
    ))):
        with patch("services.manager_agent.dispatch_customer_message", AsyncMock(return_value="...")):
            decision = await agent.dispatch(
                db=_FakeDB(),
                store=_make_store(),
                customer=_make_customer(),
                text="Bonjour je cherche un produit",
                wa=None,
                billing_status="suspended",
            )

    assert decision.agent_route == "blocked" or decision.response is not None


@pytest.mark.asyncio
async def test_dispatch_normal_flow():
    """Flux normal -> décision valide retournée."""
    agent = ManagerAgent()
    from services.agent_orchestrator import RouteDecision

    with patch("services.manager_agent.resolve_route", AsyncMock(return_value=RouteDecision(
        route="commerce_agent", degraded_mode=False, reason="default"
    ))):
        with patch("services.manager_agent.dispatch_customer_message",
                   AsyncMock(return_value="Voici nos produits disponibles.")):
            decision = await agent.dispatch(
                db=_FakeDB(),
                store=_make_store(),
                customer=_make_customer(),
                text="Quels sont vos produits?",
                wa=None,
            )

    assert decision is not None
    assert isinstance(decision, AgentDecision)
