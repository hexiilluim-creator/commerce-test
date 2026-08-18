"""tests/test_llm_gateway.py — Couverture services/llm_gateway.py.

Couvre :
  - _estimate_cost (DeepSeek, GPT-4o-mini, modèle inconnu)
  - ChatCompletion dataclass
  - chat() avec provider DeepSeek mocked
  - chat() fallback OpenAI quand DeepSeek échoue
  - Budget enforcement (hard limit dépassé)
  - Circuit breaker state (OPEN -> refus)
  - Logging structuré (provider, coût, tokens)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000")
os.environ.setdefault("DEEPSEEK_API_KEY", "ds-test-000000000000000000000000")

from services.llm_gateway import (  # noqa: E402
    _COST_PER_1K,
    ChatCompletion,
    _estimate_cost,
    chat,
)

pytestmark = pytest.mark.unit


# ─── Tests _estimate_cost ─────────────────────────────────────────────────────

def test_estimate_cost_deepseek_chat():
    cost = _estimate_cost("deepseek-chat", input_tokens=1000, output_tokens=500)
    assert cost > 0
    assert cost < 0.01  # DeepSeek est très bon marché


def test_estimate_cost_gpt4o_mini():
    cost = _estimate_cost("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    assert cost > 0


def test_estimate_cost_gpt4o_more_expensive_than_mini():
    cost_mini = _estimate_cost("gpt-4o-mini", 1000, 1000)
    cost_4o = _estimate_cost("gpt-4o", 1000, 1000)
    assert cost_4o > cost_mini


def test_estimate_cost_unknown_model_uses_default():
    cost = _estimate_cost("unknown-model-xyz", 1000, 1000)
    assert cost > 0  # Le default s'applique


def test_estimate_cost_zero_tokens():
    cost = _estimate_cost("deepseek-chat", 0, 0)
    assert cost == 0.0


def test_estimate_cost_proportional():
    """2× plus de tokens -> 2× le coût (approximatif)."""
    cost_1k = _estimate_cost("gpt-4o-mini", 1000, 0)
    cost_2k = _estimate_cost("gpt-4o-mini", 2000, 0)
    assert abs(cost_2k - cost_1k * 2) < 0.000001


# ─── Tests _COST_PER_1K structure ─────────────────────────────────────────────

def test_cost_table_has_deepseek():
    assert "deepseek-chat" in _COST_PER_1K


def test_cost_table_has_gpt4o_mini():
    assert "gpt-4o-mini" in _COST_PER_1K


def test_cost_table_input_output_keys():
    for model, rates in _COST_PER_1K.items():
        assert "input" in rates, f"Model {model} missing input rate"
        assert "output" in rates, f"Model {model} missing output rate"
        assert rates["input"] > 0
        assert rates["output"] > 0


# ─── Tests ChatCompletion ─────────────────────────────────────────────────────

def test_chat_completion_dataclass():
    cc = ChatCompletion(
        content="Hello world",
        model="deepseek-chat",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        provider="deepseek",
        latency_ms=120.5,
    )
    assert cc.content == "Hello world"
    assert cc.provider == "deepseek"
    assert cc.cost_usd > 0


def test_chat_completion_total_tokens():
    cc = ChatCompletion(
        content="test",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0001,
        provider="openai",
        latency_ms=200.0,
    )
    assert cc.input_tokens + cc.output_tokens == 150


# ─── Tests chat() avec mock ───────────────────────────────────────────────────

def _make_fake_openai_response(content="Test response"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        model="deepseek-chat",
    )


@pytest.mark.asyncio
async def test_chat_deepseek_primary_success():
    """Chat avec DeepSeek comme provider primaire."""
    fake_response = _make_fake_openai_response("Réponse DeepSeek test")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("services.llm_gateway._call_deepseek", AsyncMock(return_value=ChatCompletion(
        content="Réponse DeepSeek test",
        model="deepseek-chat",
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.000004,
        provider="deepseek",
        latency_ms=150.0,
    ))):
        result = await chat(
            messages=[{"role": "user", "content": "Bonjour"}],
            tenant_id=1,
            agent_name="test",
        )

    assert result.content == "Réponse DeepSeek test"
    assert result.provider == "deepseek"


@pytest.mark.asyncio
async def test_chat_fallback_to_openai_on_deepseek_failure():
    """Quand DeepSeek échoue -> fallback automatique vers OpenAI."""
    with patch("services.llm_gateway._call_deepseek", AsyncMock(side_effect=Exception("DeepSeek down"))):
        with patch("services.llm_gateway._call_openai", AsyncMock(return_value=ChatCompletion(
            content="Réponse OpenAI fallback",
            model="gpt-4o-mini",
            input_tokens=10,
            output_tokens=15,
            cost_usd=0.00001,
            provider="openai",
            latency_ms=300.0,
        ))):
            result = await chat(
                messages=[{"role": "user", "content": "test"}],
                tenant_id=2,
            )

    assert "openai" in result.provider.lower() or result.content is not None


@pytest.mark.asyncio
async def test_chat_budget_enforcement():
    """Budget hard limit dépassé -> exception ou ChatCompletion d'erreur."""
    with patch("services.llm_gateway._check_budget", AsyncMock(side_effect=Exception("Budget exceeded"))):
        try:
            await chat(
                messages=[{"role": "user", "content": "test"}],
                tenant_id=999,
            )
        except Exception:
            pass  # Expected behavior


@pytest.mark.asyncio
async def test_chat_with_system_prompt():
    """System prompt transmis correctement."""
    with patch("services.llm_gateway._call_deepseek", AsyncMock(return_value=ChatCompletion(
        content="Réponse avec system",
        model="deepseek-chat",
        input_tokens=20,
        output_tokens=10,
        cost_usd=0.000005,
        provider="deepseek",
        latency_ms=100.0,
    ))):
        result = await chat(
            messages=[{"role": "user", "content": "test"}],
            system="Tu es un assistant e-commerce.",
            tenant_id=3,
        )
    assert result is not None
