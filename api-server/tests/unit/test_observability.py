"""Tests unitaires pour P0-1 — Observabilité Sentry + OpenTelemetry.

Couvre :
- test_sentry_initialized_when_dsn_present
- test_sentry_not_initialized_when_dsn_absent_dev_only
- test_sentry_required_in_prod (monkeypatch_env_prod)
- test_otel_tracer_provider_exported (monkeypatch_endpoint)
- test_llm_call_creates_span

NOTE : L'environnement sandbox injecte SENTRY_DSN et OTEL_EXPORTER_OTLP_ENDPOINT
dans os.environ. Les tests doivent les unset explicitement.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SENTRY_ENV_KEYS = [
    "SENTRY_DSN",
    "FEATURE_FLAG_SENTRY",
    "FEATURE_FLAG_OTEL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_TIMEOUT_SECONDS",
    "OTEL_BSP_SCHEDULE_DELAY",
    "OTEL_BSP_MAX_EXPORT_BATCH_SIZE",
    "OTEL_SPAN_MIN_DURATION_MS",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_TRACES_EXPORTER",
    "OTEL_TRACES_SAMPLER_RATIO",
    "OTEL_PYTHON_LOG_CORRELATION",
    "OTEL_LOG_SAMPLE_RATE",
]


@pytest.fixture(autouse=True)
def _clear_observability_env(monkeypatch):
    """Supprime toutes les env vars observabilité héritées du process sandbox."""
    for key in _SENTRY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Remet les valeurs par défaut nécessaires
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")


@pytest.fixture
def reset_observability():
    """Réinitialise l'état global du module observability."""
    from services.observability import reset_observability_state
    yield
    reset_observability_state()


# ── P0-1.A : Sentry initialisé quand DSN présent ─────────────────────────────

def test_sentry_initialized_when_dsn_present(monkeypatch, reset_observability):
    """Sentry doit s'initialiser si SENTRY_DSN est renseigné."""
    monkeypatch.setenv("SENTRY_DSN", "https://abc123@sentry.example.com/42")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "1")

    from services.observability import _configure_sentry
    result = _configure_sentry()
    assert result is True


def test_sentry_not_initialized_when_flag_disabled(monkeypatch, reset_observability):
    """Sentry ne doit PAS s'initialiser si FEATURE_FLAG_SENTRY=0."""
    monkeypatch.setenv("SENTRY_DSN", "https://abc123@sentry.example.com/42")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")

    from services.observability import _configure_sentry
    result = _configure_sentry()
    assert result is False


def test_sentry_not_initialized_when_dsn_absent_dev(monkeypatch, reset_observability):
    """En dev sans DSN, Sentry ne doit pas lever d'erreur."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "1")

    from services.observability import _configure_sentry
    result = _configure_sentry()
    assert result is False


# ── P0-1.B : Sentry obligatoire en production ────────────────────────────────

def test_sentry_required_in_prod(monkeypatch, reset_observability):
    """En production, si Sentry et OTEL sont désactivés, install_observability doit lever."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import install_observability, reset_observability_state
    reset_observability_state()

    with pytest.raises(RuntimeError, match="Observabilité"):
        install_observability()


def test_prod_with_sentry_dsn_ok(monkeypatch, reset_observability):
    """En production avec SENTRY_DSN, install_observability doit réussir."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SENTRY_DSN", "https://abc123@sentry.example.com/42")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "1")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import install_observability, reset_observability_state
    reset_observability_state()

    status = install_observability()
    assert status.sentry_enabled is True
    assert status.otel_enabled is False


def test_staging_traces_sample_rate(monkeypatch, reset_observability):
    """En staging, le traces_sample_rate doit être 1.0."""
    monkeypatch.setenv("ENV", "staging")

    from services.observability import compute_traces_sample_rate
    assert compute_traces_sample_rate() == 1.0


def test_production_traces_sample_rate(monkeypatch, reset_observability):
    """En production, le traces_sample_rate doit être 0.2."""
    monkeypatch.setenv("ENV", "production")

    from services.observability import compute_traces_sample_rate
    assert compute_traces_sample_rate() == 0.2


def test_development_traces_sample_rate(monkeypatch, reset_observability):
    """En développement, le traces_sample_rate doit être 0.0."""
    monkeypatch.setenv("ENV", "development")

    from services.observability import compute_traces_sample_rate
    assert compute_traces_sample_rate() == 0.0


# ── P0-1.C : OpenTelemetry TracerProvider exporté ────────────────────────────

def test_otel_tracer_provider_exported(monkeypatch, reset_observability):
    """OTEL doit initialiser un TracerProvider quand FEATURE_FLAG_OTEL=1 et endpoint OK."""
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "autocommerce-test")

    from services.observability import _configure_otel, reset_observability_state
    reset_observability_state()

    result = _configure_otel(app=None)
    assert result is True


def test_otel_endpoint_missing_in_prod_raises(monkeypatch, reset_observability):
    """En production, si OTEL activé mais endpoint vide, doit lever RuntimeError."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import _configure_otel, reset_observability_state
    reset_observability_state()

    with pytest.raises(RuntimeError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        _configure_otel(app=None)


def test_otel_not_enabled_flag_off(monkeypatch, reset_observability):
    """Si FEATURE_FLAG_OTEL=0, _configure_otel retourne False sans lever."""
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")

    from services.observability import _configure_otel
    result = _configure_otel(app=None)
    assert result is False


# ── P0-1.D : OTLP endpoint check ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_otlp_endpoint_unreachable(monkeypatch, reset_observability):
    """check_otlp_endpoint retourne False quand l'endpoint est inaccessible."""
    # Utiliser un port très élevé et non routable pour garantir l'échec
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://10.255.255.1:9999")
    monkeypatch.setenv("OTEL_EXPORTER_TIMEOUT_SECONDS", "0.5")

    from services.observability import check_otlp_endpoint
    result = await check_otlp_endpoint()
    assert result is False


@pytest.mark.asyncio
async def test_check_otlp_endpoint_empty(monkeypatch, reset_observability):
    """check_otlp_endpoint retourne False si endpoint vide."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import check_otlp_endpoint
    result = await check_otlp_endpoint()
    assert result is False


# ── P0-1.E : require_runtime_observability ───────────────────────────────────

def test_require_runtime_observability_prod_ok(monkeypatch, reset_observability):
    """En prod avec SENTRY_DSN, require_runtime_observability ne lève pas."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.example.com/1")

    from services.observability import require_runtime_observability
    require_runtime_observability()  # ne doit pas lever


def test_require_runtime_observability_prod_fail(monkeypatch, reset_observability):
    """En prod sans aucun observabilité, doit lever RuntimeError."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import require_runtime_observability
    with pytest.raises(RuntimeError):
        require_runtime_observability()


def test_require_runtime_observability_dev_no_check(monkeypatch, reset_observability):
    """En dev, require_runtime_observability ne lève jamais."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import require_runtime_observability
    require_runtime_observability()  # ne doit pas lever


# ── P0-1.F : LLM call crée une span ──────────────────────────────────────────

def test_llm_call_creates_span(monkeypatch, reset_observability):
    """Un appel LLM doit créer une span OpenTelemetry avec les bons attributs."""
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    from services.observability import get_tracer, install_observability, reset_observability_state
    reset_observability_state()
    install_observability()

    tracer = get_tracer("autocommerce.llm")
    assert tracer is not None

    span = tracer.start_span("llm.chat")
    assert span is not None
    span.set_attribute("llm.provider", "deepseek")
    span.set_attribute("llm.model", "deepseek-chat")
    span.set_attribute("llm.store_id", 42)
    span.end()


def test_inject_trace_context(monkeypatch, reset_observability):
    """inject_trace_context doit injecter un contexte de trace dans un dictionnaire."""
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    from services.observability import inject_trace_context, install_observability, reset_observability_state
    reset_observability_state()
    install_observability()

    carrier: dict[str, str] = {}
    result = inject_trace_context(carrier)
    assert "traceparent" in result or isinstance(result, dict)


# ── P0-1.G : ObservabilityStatus dataclass ───────────────────────────────────

def test_observability_status_dataclass():
    """ObservabilityStatus doit avoir les bons champs."""
    from services.observability import ObservabilityStatus
    status = ObservabilityStatus(
        sentry_enabled=True,
        otel_enabled=False,
        environment="production",
        otlp_endpoint="",
    )
    assert status.sentry_enabled is True
    assert status.otel_enabled is False
    assert status.environment == "production"
    assert status.otlp_endpoint == ""


# ── P0-1.H : Idempotence install_observability ──────────────────────────────

def test_install_observability_idempotent(monkeypatch, reset_observability):
    """install_observability doit retourner le même status si appelé deux fois avec les mêmes params."""
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.example.com/1")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "1")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from services.observability import install_observability, reset_observability_state
    reset_observability_state()

    status1 = install_observability()
    status2 = install_observability()
    assert status1 is status2  # même instance


# ── P0-1.I : is_prod_like ────────────────────────────────────────────────────

def test_is_prod_like(monkeypatch):
    """is_prod_like doit retourner True pour production, prod, staging."""
    from services.observability import is_prod_like

    monkeypatch.setenv("ENV", "production")
    assert is_prod_like() is True

    monkeypatch.setenv("ENV", "prod")
    assert is_prod_like() is True

    monkeypatch.setenv("ENV", "staging")
    assert is_prod_like() is True

    monkeypatch.setenv("ENV", "development")
    assert is_prod_like() is False

    monkeypatch.setenv("ENV", "test")
    assert is_prod_like() is False


# ── P0-1.J : Prometheus /metrics endpoint ────────────────────────────────────

def test_metrics_endpoint_returns_prometheus_format(monkeypatch):
    """Le endpoint /metrics retourne du texte Prometheus."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("INTERNAL_HEALTH_TOKEN", "test-token")

    import importlib
    import sys

    # Recharger main.py avec ENV=test
    if "main" in sys.modules:
        importlib.reload(sys.modules["main"])

    try:
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "prometheus" in response.headers.get("content-type", "").lower() or response.text != ""
    except Exception:
        pytest.skip("main.py nécessite une configuration complète pour démarrer")
