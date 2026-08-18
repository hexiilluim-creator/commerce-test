from __future__ import annotations

from unittest.mock import patch

import pytest

from services.llm_gateway import LLMConfig, guard_provider

# P0-fix (audit indépendant) : guard_provider() ne lit plus jamais
# os.environ("ENV") — il ne dépend que de settings.ENV. Le fixture
# autouse qui supprimait la variable d'environnement OS avant chaque test
# est donc retiré : il masquait le vrai bug (priorité os.environ sur
# settings.ENV dans le code source) sans le corriger. Ces tests
# vérifient maintenant le comportement réel de la fonction, y compris
# si une variable ENV traîne au niveau OS/conteneur (cas réel de
# docker-compose.test.yml qui fixe ENV=test).

@pytest.mark.unit
def test_stub_blocked_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.OPENAI_API_KEY = "sk-test-123"
        mock_settings.DEEPSEEK_API_KEY = "sk-test-123"
        with pytest.raises(RuntimeError):
            guard_provider(LLMConfig(provider="stub", model="stub-1"))

@pytest.mark.unit
def test_openai_requires_key_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.OPENAI_API_KEY = ""
        with pytest.raises(RuntimeError):
            guard_provider(LLMConfig(provider="openai", model="gpt-4o-mini"))

@pytest.mark.unit
def test_deepseek_requires_key_in_prod():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.DEEPSEEK_API_KEY = ""
        with pytest.raises(RuntimeError):
            guard_provider(LLMConfig(provider="deepseek", model="deepseek-chat"))

@pytest.mark.unit
def test_stub_allowed_in_development():
    with patch("services.llm_gateway.settings") as mock_settings:
        mock_settings.ENV = "development"
        # Should not raise
        guard_provider(LLMConfig(provider="stub", model="stub-1"))
