from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException

from config import settings
from services.email_sender import EmailSender
from services.jwt_rotation import current_rotation_state, rotate_tokens

router = APIRouter(prefix="/_internal", tags=["Internal Ops"])


def _ensure_internal_token(x_internal_token: str | None) -> None:
    if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.INTERNAL_HEALTH_TOKEN):
        raise HTTPException(status_code=403, detail="X-Internal-Token missing or invalid")


@router.get("/email/health")
async def internal_email_health(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _ensure_internal_token(x_internal_token)
    sender = EmailSender()
    ok = await sender.ping()
    if not ok:
        raise HTTPException(status_code=503, detail="SMTP unavailable")
    return {"status": "ok", "smtp_host": settings.SMTP_HOST, "smtp_port": settings.SMTP_PORT}


@router.post("/jwt/rotate")
async def internal_jwt_rotate(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _ensure_internal_token(x_internal_token)
    result = rotate_tokens(actor="internal_api")
    result["state"] = current_rotation_state()
    return result
