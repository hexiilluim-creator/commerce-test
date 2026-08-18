from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from middleware.trace_id import TraceIDMiddleware, get_trace_id


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIDMiddleware)

    @app.get("/trace")
    async def trace_endpoint(request: Request) -> dict[str, str]:
        return {
            "state_trace_id": request.state.trace_id,
            "context_trace_id": get_trace_id(),
        }

    return app


def test_trace_id_middleware_preserves_incoming_header() -> None:
    client = TestClient(_build_app())

    response = client.get("/trace", headers={"X-Request-ID": "req-fixed-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-fixed-123"
    assert response.json() == {
        "state_trace_id": "req-fixed-123",
        "context_trace_id": "req-fixed-123",
    }


def test_trace_id_middleware_generates_and_propagates_header() -> None:
    client = TestClient(_build_app())

    response = client.get("/trace")
    generated = response.headers["X-Request-ID"]

    assert response.status_code == 200
    assert generated
    assert response.json() == {
        "state_trace_id": generated,
        "context_trace_id": generated,
    }
