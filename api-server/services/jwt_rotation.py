"""JWT rotation helpers with transitional key support and kill-switch cutoff."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError, PyJWTError

logger = logging.getLogger(__name__)

_invalid_before_epoch: int = 0


def _verification_keys() -> list[str]:
    from config import settings

    keys = [settings.JWT_SECRET_KEY]
    raw = (settings.JWT_SECRET_KEYS_JSON or "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, list):
                keys.extend(str(k) for k in extra if k)
        except (ValueError, TypeError) as exc:
            logger.warning("jwt_rotation: JWT_SECRET_KEYS_JSON invalide, ignorée: %s", exc)
    return keys


def encode_jwt(payload: dict, algorithm: str = "HS256") -> str:
    from config import settings

    payload = dict(payload)
    payload.setdefault("iat", int(time.time()))
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=algorithm)


def decode_jwt(token: str, algorithms: list[str] | None = None) -> dict[str, Any]:
    algos = algorithms or ["HS256"]
    keys = _verification_keys()
    last_exc: PyJWTError | None = None
    for key in keys:
        try:
            decoded = jwt.decode(token, key, algorithms=algos)
            issued_at = int(decoded.get("iat", 0) or 0)
            if issued_at and issued_at < _invalid_before_epoch:
                raise InvalidTokenError("token invalidé par rotation")
            return decoded
        except PyJWTError as exc:
            last_exc = exc
            continue
    raise last_exc or InvalidTokenError("JWT invalide")


def rotate_tokens(*, actor: str = "system") -> dict[str, Any]:
    global _invalid_before_epoch
    previous = _invalid_before_epoch
    # Le cutoff est exprimé en secondes Unix et ne doit jamais être futur.
    _invalid_before_epoch = int(time.time())
    result = {
        "rotated": True,
        "invalid_before_epoch": _invalid_before_epoch,
        "previous_invalid_before_epoch": previous,
        "actor": actor,
    }
    logger.warning("jwt_rotate", extra=result)
    return result


def current_rotation_state() -> dict[str, Any]:
    return {"invalid_before_epoch": _invalid_before_epoch}
