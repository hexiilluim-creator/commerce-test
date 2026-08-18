"""Preflight production readiness checks for secrets and critical integrations."""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import string
import sys
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger("preflight")

_PROD_ENVS = {"production", "prod", "staging"}
_PLACEHOLDER_TOKENS = {
    "",
    "changeme",
    "change_me",
    "your_secret_here",
    "replace_me",
    "placeholder",
    "example",
    "password",
    "secret",
    "todo",
}


@dataclass
class SecretCheck:
    key: str
    label: str
    required_when: Callable[[], bool]
    validator: Callable[[str], str | None] | None = None


def _env() -> str:
    return os.getenv("ENV", "production").strip().lower()


def _is_prod() -> bool:
    return _env() in _PROD_ENVS


def _normalize_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _printable_ascii(value: str) -> bool:
    return all(ch in string.printable and ch not in "\r\n\t\x0b\x0c" for ch in value)


def _shannon_entropy_per_char(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def _is_placeholder(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in _PLACEHOLDER_TOKENS:
        return True
    return any(token and token in normalized for token in _PLACEHOLDER_TOKENS)


def _require(value: str, *, min_length: int = 1, printable_ascii: bool = False) -> str | None:
    if not value:
        return "absent ou vide"
    if _is_placeholder(value):
        return "placeholder détecté"
    if len(value) < min_length:
        return f"trop court ({len(value)} < {min_length})"
    if printable_ascii and not _printable_ascii(value):
        return "doit être ASCII imprimable"
    return None


def _validate_secret_key(value: str) -> str | None:
    err = _require(value, min_length=64, printable_ascii=True)
    if err:
        return err
    entropy = _shannon_entropy_per_char(value)
    if entropy < 4.5:
        return f"entropie insuffisante ({entropy:.2f} < 4.5 bits/car)"
    return None


def _validate_jwt_secret(value: str) -> str | None:
    return _require(value, min_length=32, printable_ascii=True)


def _validate_fernet_key(value: str) -> str | None:
    err = _require(value, min_length=32)
    if err:
        return err
    try:
        decoded = base64.urlsafe_b64decode(value.encode())
    except Exception:
        return "clé Fernet invalide (base64)"
    if len(decoded) != 32:
        return f"clé Fernet invalide ({len(decoded)} octets décodés, 32 attendus)"
    return None


def _validate_live_stripe(value: str) -> str | None:
    err = _require(value, min_length=16)
    if err:
        return err
    if not value.startswith("sk_live_"):
        return "doit commencer par sk_live_"
    return None


def _validate_non_empty_csv(value: str) -> str | None:
    err = _require(value, min_length=1)
    if err:
        return err
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return "liste vide"
    return None


def _validate_url(value: str) -> str | None:
    err = _require(value, min_length=8)
    if err:
        return err
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https", "grpc", "grpcs"} or not parsed.netloc:
        return "URL invalide"
    return None


def _llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    return provider or "deepseek"


def _secret_checks() -> list[SecretCheck]:
    return [
        SecretCheck("SECRET_KEY", "SECRET_KEY", lambda: _is_prod(), _validate_secret_key),
        SecretCheck("JWT_SECRET_KEY", "JWT_SECRET_KEY", lambda: _is_prod(), _validate_jwt_secret),
        SecretCheck("ENCRYPTION_KEY", "ENCRYPTION_KEY", lambda: _is_prod(), _validate_fernet_key),
        SecretCheck("SMTP_HOST", "SMTP_HOST", lambda: _is_prod() and _normalize_bool(os.getenv("STRIPE_ENABLED", "0")), lambda v: _require(v, min_length=1)),
        SecretCheck("SMTP_PORT", "SMTP_PORT", lambda: _is_prod() and _normalize_bool(os.getenv("STRIPE_ENABLED", "0")), lambda v: _require(v, min_length=1)),
        SecretCheck("ALLOWED_HOSTS", "ALLOWED_HOSTS", lambda: _is_prod(), _validate_non_empty_csv),
        SecretCheck("CORS_ORIGINS", "CORS_ORIGINS", lambda: _is_prod(), _validate_non_empty_csv),
        SecretCheck("SENTRY_DSN", "SENTRY_DSN", lambda: _is_prod() and _normalize_bool(os.getenv("FEATURE_FLAG_SENTRY", "1")), _validate_url),
        SecretCheck("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT", lambda: _is_prod() and _normalize_bool(os.getenv("FEATURE_FLAG_OTEL", "0")), _validate_url),
        SecretCheck("OPENAI_API_KEY", "OPENAI_API_KEY", lambda: _is_prod() and _llm_provider() == "openai", lambda v: _require(v, min_length=20)),
        SecretCheck("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", lambda: _is_prod() and _llm_provider() == "deepseek", lambda v: _require(v, min_length=20)),
        SecretCheck("STORE_OPENAI_KEY", "STORE_OPENAI_KEY", lambda: _is_prod() and _normalize_bool(os.getenv("FEATURE_FLAG_BYOK_OPENAI", "0")), lambda v: _require(v, min_length=20)),
        SecretCheck("STRIPE_SECRET_KEY", "STRIPE_SECRET_KEY", lambda: _is_prod() and _normalize_bool(os.getenv("STRIPE_ENABLED", "0")), _validate_live_stripe),
    ]


async def _check_redis() -> str | None:
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return "REDIS_URL absent"
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(redis_url, decode_responses=True)
        pong = await asyncio.wait_for(client.ping(), timeout=3.0)
        await client.aclose()
        if pong is not True:
            return "redis ping KO"
        return None
    except Exception as exc:  # noqa: BLE001
        return f"redis ping KO: {type(exc).__name__}"


async def _check_database_url() -> str | None:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return "DATABASE_URL absent"
    normalized = database_url.lower()
    if not normalized.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://")):
        return "DATABASE_URL doit pointer vers PostgreSQL"
    if "postgres" not in normalized:
        return "DATABASE_URL invalide"
    return None


async def _check_smtp_socket() -> str | None:
    host = os.getenv("SMTP_HOST", "")
    if not host:
        return "SMTP_HOST absent"
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return "SMTP_PORT invalide"
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"SMTP indisponible: {type(exc).__name__}"


async def _check_otlp_socket() -> str | None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return "OTEL_EXPORTER_OTLP_ENDPOINT absent"
    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme in {"https", "grpcs"} else 80)
    if not host:
        return "OTEL_EXPORTER_OTLP_ENDPOINT invalide"
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"OTLP indisponible: {type(exc).__name__}"


def _consistency_checks() -> list[str]:
    errors: list[str] = []
    secret_key = os.getenv("SECRET_KEY", "")
    jwt_secret = os.getenv("JWT_SECRET_KEY", "")
    encryption_key = os.getenv("ENCRYPTION_KEY", "")
    if secret_key and encryption_key and secret_key == encryption_key:
        errors.append("SECRET_KEY et ENCRYPTION_KEY doivent être distinctes")
    if secret_key and jwt_secret and secret_key == jwt_secret:
        errors.append("JWT_SECRET_KEY doit être distinct de SECRET_KEY")
    if _is_prod() and _llm_provider() == "stub":
        errors.append("LLM_PROVIDER=stub interdit en production/staging")
    if _normalize_bool(os.getenv("FEATURE_FLAG_BYOK_OPENAI", "0")) and not os.getenv("STORE_OPENAI_KEY"):
        errors.append("FEATURE_FLAG_BYOK_OPENAI=1 exige STORE_OPENAI_KEY non vide")
    return errors


async def collect_preflight_report() -> dict:
    env = _env()
    errors: list[str] = []
    warnings: list[str] = []

    for check in _secret_checks():
        if not check.required_when():
            continue
        value = os.getenv(check.key, "")
        err = check.validator(value) if check.validator else _require(value)
        if err:
            errors.append(f"{check.label}: {err}")

    errors.extend(_consistency_checks())

    if _is_prod():
        db_err, redis_err = await asyncio.gather(_check_database_url(), _check_redis())
        if db_err:
            errors.append(f"DATABASE_URL: {db_err}")
        if redis_err:
            errors.append(f"REDIS_URL: {redis_err}")
        if _normalize_bool(os.getenv("STRIPE_ENABLED", "0")):
            smtp_err = await _check_smtp_socket()
            if smtp_err:
                errors.append(f"SMTP: {smtp_err}")
        if _normalize_bool(os.getenv("FEATURE_FLAG_OTEL", "0")):
            otlp_err = await _check_otlp_socket()
            if otlp_err:
                errors.append(f"OTLP: {otlp_err}")
    else:
        if not os.getenv("SMTP_HOST"):
            warnings.append("SMTP_HOST absent en environnement non-production")

    report = {
        "ok": not errors,
        "env": env,
        "timestamp": int(time.time()),
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "llm_provider": _llm_provider(),
            "feature_flag_sentry": _normalize_bool(os.getenv("FEATURE_FLAG_SENTRY", "1")),
            "feature_flag_otel": _normalize_bool(os.getenv("FEATURE_FLAG_OTEL", "0")),
            "kms_provider": os.getenv("KMS_PROVIDER", "local"),
        },
    }
    logger.info("preflight_executed", report=report)
    return report


def run_preflight(env: str | None = None) -> dict:
    if env:
        os.environ["ENV"] = env
    report = asyncio.run(collect_preflight_report())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)
    return report


async def run_startup_preflight() -> dict:
    report = await collect_preflight_report()
    if not report["ok"]:
        raise RuntimeError("Preflight bloquant: " + "; ".join(report["errors"]))
    return report


if __name__ == "__main__":
    run_preflight()
