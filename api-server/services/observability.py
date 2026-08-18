"""Observability bootstrap: Sentry, OpenTelemetry and lightweight health helpers."""
from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog

from config import settings

logger = structlog.get_logger("observability")
_PROD_ENVS = {"production", "prod", "staging"}


@dataclass(slots=True)
class ObservabilityStatus:
    sentry_enabled: bool
    otel_enabled: bool
    environment: str
    otlp_endpoint: str


_installed_status: ObservabilityStatus | None = None


def reset_observability_state() -> None:
    """Réinitialise l’état d’installation global de l’observabilité.

    Cette fonction est destinée aux tests et aux reconfigurations contrôlées :
    elle rend le prochain appel à :func:`install_observability` effectif au
    lieu de retourner le statut mis en cache du processus.
    """
    global _installed_status
    _installed_status = None


def _env_value(name: str, default=None):
    if name in os.environ:
        return os.getenv(name, default)
    # Les tests et les déploiements pilotés par ENV doivent pouvoir supprimer
    # explicitement une valeur héritée du singleton Settings.
    if "ENV" in os.environ and name != "ENV":
        return default
    return getattr(settings, name, default)


def _flag(name: str, default: bool = False) -> bool:
    value = _env_value(name, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _env() -> str:
    return str(_env_value("ENV", "production") or "production").strip().lower()


def is_prod_like() -> bool:
    return _env() in _PROD_ENVS


def compute_traces_sample_rate() -> float:
    env = _env()
    if env in {"production", "prod"}:
        return 0.2
    if env == "staging":
        return 1.0
    return 0.0


def _otlp_host_port(endpoint: str) -> tuple[str, int] | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme in {"https", "grpcs"} else 80)
    if not host:
        return None
    return host, port


async def check_otlp_endpoint() -> bool:
    target = _otlp_host_port(_env_value("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    if not target:
        return False
    host, port = target
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=settings.OTEL_EXPORTER_TIMEOUT_SECONDS)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("otlp_endpoint_unreachable", endpoint=_env_value("OTEL_EXPORTER_OTLP_ENDPOINT", ""), error=str(exc))
        return False


def _configure_sentry() -> bool:
    dsn = _env_value("SENTRY_DSN", None)
    if not dsn or not _flag("FEATURE_FLAG_SENTRY", True):
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=compute_traces_sample_rate(),
            environment=_env(),
            release=os.getenv("RELEASE_VERSION", os.getenv("VERSION", "unknown")),
        )
        logger.info("sentry_initialized", environment=settings.ENV)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("sentry_initialization_failed", error=str(exc))
        if is_prod_like():
            raise
        return False


def _configure_otel(app=None) -> bool:
    if not _flag("FEATURE_FLAG_OTEL", False):
        return False
    endpoint = _env_value("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        if is_prod_like():
            raise RuntimeError("OTEL_EXPORTER_OTLP_ENDPOINT manquant")
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        resource = Resource.create({
            "service.name": _env_value("OTEL_SERVICE_NAME", "autocommerce"),
            "deployment.environment": _env(),
            "service.version": os.getenv("RELEASE_VERSION", os.getenv("VERSION", "unknown")),
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        set_global_textmap(TraceContextTextMapPropagator())
        if app is not None:
            try:
                FastAPIInstrumentor.instrument_app(app)
            except Exception:
                pass
        logger.info("otel_initialized", endpoint=endpoint)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("otel_initialization_failed", error=str(exc), endpoint=endpoint)
        if is_prod_like():
            raise
        return False


def install_observability(app=None) -> ObservabilityStatus:
    global _installed_status
    if _installed_status is not None:
        return _installed_status
    sentry_enabled = _configure_sentry()
    otel_enabled = _configure_otel(app)
    if is_prod_like() and not sentry_enabled and not otel_enabled:
        raise RuntimeError("Observabilité désactivée en production/staging (Sentry/OTEL)")
    _installed_status = ObservabilityStatus(
        sentry_enabled=sentry_enabled,
        otel_enabled=otel_enabled,
        environment=_env(),
        otlp_endpoint=_env_value("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
    )
    return _installed_status


def get_tracer(name: str = "autocommerce"):
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        return None


def inject_trace_context(carrier: dict[str, str]) -> dict[str, str]:
    try:
        from opentelemetry.propagate import inject
        inject(carrier)
    except Exception:
        return carrier
    return carrier


def require_runtime_observability() -> None:
    if is_prod_like() and not (_env_value("SENTRY_DSN", None) or _env_value("OTEL_EXPORTER_OTLP_ENDPOINT", "")):
        raise RuntimeError("En production/staging, SENTRY_DSN ou OTEL_EXPORTER_OTLP_ENDPOINT doit être configuré")
