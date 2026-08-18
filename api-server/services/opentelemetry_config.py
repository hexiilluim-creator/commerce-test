"""services/opentelemetry_config.py — OpenTelemetry Distributed Tracing (Phase 4).

Référencé dans main.py — graceful skip si opentelemetry non installé.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_opentelemetry(app, engine=None) -> None:
    """Configure OpenTelemetry avec exporteur OTLP si disponible."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()

        otlp_endpoint = os.getenv("OTLP_ENDPOINT", "")
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info("OpenTelemetry OTLP exporter configured: %s", otlp_endpoint)
            except ImportError:
                logger.warning("opentelemetry-exporter-otlp-proto-grpc not installed")
        else:
            logger.info("OpenTelemetry configured (no OTLP endpoint — traces not exported)")

        trace.set_tracer_provider(provider)

        # Auto-instrumentation FastAPI
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI OpenTelemetry instrumented")
        except ImportError:
            pass

        # Auto-instrumentation SQLAlchemy
        if engine is not None:
            try:
                from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
                SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
                logger.info("SQLAlchemy OpenTelemetry instrumented")
            except (ImportError, Exception) as exc:
                logger.debug("SQLAlchemy OTel instrumentation skipped: %s", exc)

    except ImportError as exc:
        raise ImportError(f"opentelemetry not installed: {exc}") from exc
