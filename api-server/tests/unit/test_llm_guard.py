from __future__ import annotations

from unittest.mock import patch

import pytest

import services.llm_gateway

# P0-fix (audit indépendant) : guard_provider() ne lit plus jamais
# os.environ("ENV") — il ne dépend que de settings.ENV (voir
# services/llm_gateway.py). Les contournements précédents (monkeypatch.setenv
# sur ENV, importlib.reload du module) étaient nécessaires uniquement pour
# faire coïncider l'environnement OS avec settings.ENV et masquer le bug de
# priorité dans le code source — ils ne le vérifiaient pas. Simplifié pour
# ne patcher que settings, comme le reste de l'app le fait déjà.


@pytest.mark.unit
def test_os_env_var_never_overrides_settings(monkeypatch):
    """Régression : un ENV défini au niveau OS (ex. docker-compose.test.yml
    fixe ENV=test) ne doit JAMAIS l'emporter sur settings.ENV. C'est
    exactement le bug trouvé lors de l'audit indépendant — guard_provider()
    lisait os.getenv("ENV") en priorité, ce qui le rendait contournable dès
    qu'une variable ENV traînait au niveau OS/conteneur, y compris avec une
    valeur qui n'a rien à voir avec la configuration applicative réelle."""
    monkeypatch.setenv("ENV", "test")  # variable OS qui ne doit avoir aucun effet ici
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.OPENAI_API_KEY = ""
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY requis"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="openai", model="gpt-4o-mini"))


@pytest.mark.unit
def test_stub_blocked_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.OPENAI_API_KEY = "sk-test-123"
        mock_settings.DEEPSEEK_API_KEY = "sk-test-123"
        with pytest.raises(RuntimeError, match="interdit en production"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="stub", model="stub-1"))


@pytest.mark.unit
def test_openai_requires_key_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.OPENAI_API_KEY = ""
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY requis"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="openai", model="gpt-4o-mini"))


@pytest.mark.unit
def test_deepseek_requires_key_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.DEEPSEEK_API_KEY = ""
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY requis"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="deepseek", model="deepseek-chat"))


@pytest.mark.unit
def test_stub_allowed_in_development():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "development"
        services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="stub", model="stub-1"))


@pytest.mark.unit
def test_byok_requires_key_and_no_stub():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.FEATURE_FLAG_BYOK_OPENAI = True
        mock_settings.STORE_OPENAI_KEY = ""

        with pytest.raises(RuntimeError, match="interdit quand FEATURE_FLAG_BYOK_OPENAI est activé"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="stub", model="stub-1"))

        with pytest.raises(RuntimeError, match="STORE_OPENAI_KEY requis"):
            services.llm_gateway.guard_provider(services.llm_gateway.LLMConfig(provider="openai", model="gpt-4o-mini"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prometheus_provider_counter_incremented(monkeypatch):
    """Test that the LLM provider counter is incremented after a call."""
    from unittest.mock import AsyncMock

    from services.llm_gateway import ChatCompletion, chat
    from services.metrics import llm_provider_used_total

    try:
        initial_value = llm_provider_used_total.labels(provider="openai")._value.get()
    except Exception:
        initial_value = 0

    mock_response = ChatCompletion(
        content="test response",
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.0001,
        provider="openai",
        latency_ms=100
    )

    monkeypatch.setattr("services.llm_gateway.provider_from_settings", lambda: services.llm_gateway.LLMConfig(provider="openai", model="gpt-4o-mini"))

    with patch("services.llm_gateway._call_openai", AsyncMock(return_value=mock_response)):
        with patch("services.llm_gateway._check_budget", AsyncMock()):
            with patch("services.llm_gateway._cb_openai.is_open", return_value=False):
                with patch("services.llm_gateway._cb_deepseek.is_open", return_value=True):
                    await chat(messages=[{"role": "user", "content": "hello"}], tenant_id=1)

    final_value = llm_provider_used_total.labels(provider="openai")._value.get()
    assert final_value == initial_value + 1
