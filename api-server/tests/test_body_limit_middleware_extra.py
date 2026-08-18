from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.body_limit import BodySizeLimitMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post("/api/v1/payments/webhook/events")
    async def payments_webhook() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/ai/vision/upload")
    async def vision_upload() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/custom")
    async def custom() -> dict[str, bool]:
        return {"ok": True}

    return app



def test_body_limit_blocks_prefixed_payment_webhook_requests() -> None:
    client = TestClient(_build_app())

    response = client.post(
        "/api/v1/payments/webhook/events",
        content=b"x",
        headers={"content-length": str(70 * 1024)},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": "Request body too large",
        "max_bytes": 64 * 1024,
        "received_bytes": 70 * 1024,
    }



def test_body_limit_accepts_request_at_exact_default_limit() -> None:
    client = TestClient(_build_app())

    response = client.post(
        "/custom",
        content=b"x",
        headers={"content-length": str(1024 * 1024)},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}



def test_body_limit_uses_route_specific_larger_limit_for_ai_upload() -> None:
    client = TestClient(_build_app())

    response = client.post(
        "/api/v1/ai/vision/upload",
        content=b"x",
        headers={"content-length": str(2 * 1024 * 1024)},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}



def test_body_limit_ignores_malformed_content_length_header() -> None:
    client = TestClient(_build_app())

    response = client.post(
        "/custom",
        content=b"x",
        headers={"content-length": "not-a-number"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
