import os
from unittest.mock import patch

import pytest

from services import llm_gateway


def test_provider_selection_flags_and_costs():
    with patch.object(llm_gateway.settings, "LLM_PROVIDER", "stub"):
        assert llm_gateway.provider_from_settings() == llm_gateway.LLMConfig("stub", "stub-1")
    with patch.object(llm_gateway.settings, "LLM_PROVIDER", "openai"), patch.object(llm_gateway.settings, "OPENAI_MODEL", "gpt-4o"):
        assert llm_gateway.provider_from_settings().model == "gpt-4o"
    with patch.object(llm_gateway.settings, "FEATURE_FLAG_BYOK_OPENAI", "yes"):
        assert llm_gateway._flag_enabled("FEATURE_FLAG_BYOK_OPENAI") is True
    assert llm_gateway._estimate_cost("gpt-4o-mini", 1000, 1000) == pytest.approx(0.00075)
    assert llm_gateway._estimate_cost("unknown", 1000, 1000) == pytest.approx(0.003)


def test_guard_provider_rejects_insecure_production_configurations():
    with patch.dict(os.environ, {"ENV": "production"}, clear=False), patch.object(llm_gateway.settings, "FEATURE_FLAG_BYOK_OPENAI", False):
        with pytest.raises(RuntimeError, match="stub interdit"):
            llm_gateway.guard_provider(llm_gateway.LLMConfig("stub", "stub-1"))
        with patch.object(llm_gateway.settings, "OPENAI_API_KEY", ""):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY requis"):
                llm_gateway.guard_provider(llm_gateway.LLMConfig("openai", "gpt-4o-mini"))
        with patch.object(llm_gateway.settings, "DEEPSEEK_API_KEY", ""):
            with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY requis"):
                llm_gateway.guard_provider(llm_gateway.LLMConfig("deepseek", "deepseek-chat"))


def test_guard_provider_allows_configured_nonprod_and_byok_requires_store_key():
    with patch.dict(os.environ, {"ENV": "development"}, clear=False):
        llm_gateway.guard_provider(llm_gateway.LLMConfig("stub", "stub-1"))
    with patch.dict(os.environ, {"ENV": "production"}, clear=False), patch.object(llm_gateway.settings, "FEATURE_FLAG_BYOK_OPENAI", True), patch.object(llm_gateway.settings, "STORE_OPENAI_KEY", ""):
        with pytest.raises(RuntimeError, match="STORE_OPENAI_KEY requis"):
            llm_gateway.guard_provider(llm_gateway.LLMConfig("openai", "gpt-4o-mini"))
