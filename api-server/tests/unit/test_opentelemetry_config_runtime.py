from fastapi import FastAPI

import pytest

from services.opentelemetry_config import setup_opentelemetry


def test_setup_opentelemetry_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTLP_ENDPOINT", raising=False)
    app = FastAPI()
    try:
        setup_opentelemetry(app, engine=None)
    except ImportError as exc:
        pytest.skip(f"OpenTelemetry optional dependency absent: {exc}")


def test_setup_opentelemetry_without_endpoint_is_repeatable(monkeypatch):
    monkeypatch.delenv("OTLP_ENDPOINT", raising=False)
    try:
        app = FastAPI()
        setup_opentelemetry(app, engine=None)
        setup_opentelemetry(app, engine=None)
    except ImportError as exc:
        pytest.skip(f"OpenTelemetry optional dependency absent: {exc}")
