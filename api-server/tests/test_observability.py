from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.llm_gateway import ChatCompletion, LLMConfig, guard_provider


@pytest.fixture(autouse=True)
def reset_observability():
    import services.observability
    services.observability._installed_status = None
    yield
    services.observability._installed_status = None

@pytest.mark.unit
def test_sentry_initialized_when_dsn_present():
    with patch("services.observability.settings") as mock_settings, \
         patch("services.observability.is_prod_like", return_value=False), \
         patch("services.observability._configure_sentry", return_value=True), \
         patch("services.observability._configure_otel", return_value=False):
        mock_settings.SENTRY_DSN = "https://example@o0.ingest.sentry.io/1"
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        mock_settings.FEATURE_FLAG_SENTRY = True
        mock_settings.FEATURE_FLAG_OTEL = False
        mock_settings.ENV = "staging"
        from services.observability import install_observability
        status = install_observability()
        assert status.sentry_enabled is True

@pytest.mark.unit
def test_sentry_not_initialized_when_dsn_absent_dev_only():
    with patch("services.observability.settings") as mock_settings, \
         patch("services.observability.is_prod_like", return_value=False), \
         patch("services.observability._configure_sentry", return_value=False), \
         patch("services.observability._configure_otel", return_value=False):
        mock_settings.SENTRY_DSN = ""
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        mock_settings.FEATURE_FLAG_SENTRY = False
        mock_settings.FEATURE_FLAG_OTEL = False
        mock_settings.ENV = "development"
        from services.observability import install_observability
        status = install_observability()
        assert status.sentry_enabled is False

@pytest.mark.unit
def test_sentry_required_in_prod():
    with patch("services.observability.settings") as mock_settings, \
         patch("services.observability.is_prod_like", return_value=True), \
         patch("services.observability._configure_sentry", return_value=False), \
         patch("services.observability._configure_otel", return_value=False):
        mock_settings.SENTRY_DSN = ""
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        mock_settings.FEATURE_FLAG_SENTRY = False
        mock_settings.FEATURE_FLAG_OTEL = False
        mock_settings.ENV = "production"
        from services.observability import install_observability
        with pytest.raises(RuntimeError):
            install_observability()

@pytest.mark.unit
def test_otel_tracer_provider_exported():
    with patch("services.observability.settings") as mock_settings, \
         patch("services.observability._env", return_value="staging"):
        mock_settings.ENV = "staging"
        from services.observability import compute_traces_sample_rate
        assert compute_traces_sample_rate() == 1.0

@pytest.mark.asyncio
async def test_llm_call_creates_span():
    span = MagicMock()
    tracer = MagicMock(start_span=MagicMock(return_value=span))
    with patch("services.observability.get_tracer", return_value=tracer), \
         patch("services.llm_gateway._check_budget"), \
         patch("services.llm_gateway._call_deepseek", return_value=ChatCompletion(content="ok", model="deepseek-chat", input_tokens=10, output_tokens=5, cost_usd=0.01, provider="deepseek", latency_ms=12)), \
         patch("services.llm_gateway._record_usage"), \
         patch("services.llm_gateway._cb_deepseek.record_success"), \
         patch("services.observability.settings") as mock_settings:
        mock_settings.ENV = "test"
        mock_settings.FEATURE_FLAG_OTEL = True
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = "http://otel:4317"
        from services.llm_gateway import chat
        result = await chat([{"role": "user", "content": "hello"}], tenant_id=1)
        assert result.provider == "deepseek"
        assert span.set_attribute.called
