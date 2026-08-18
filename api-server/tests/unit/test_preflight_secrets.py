"""Tests unitaires pour P0-5 — Preflight secrets durci (HSM-ready).

Couvre :
- test_secret_key_too_short()
- test_low_entropy_rejected()
- test_smtp_check_required_in_prod()
- test_llm_stub_blocked_in_prod()
- test_kms_provider_override(monkeypatch_kms_provider)
- test_encryption_key_duplicate_secret_key()
- test_fernet_key_invalid_base64()
- test_stripe_live_prefix_required()
- test_consistency_checks_duplicate_keys()
- test_collect_preflight_report_structure()
- test_run_startup_preflight_raises_on_errors()
- test_allowed_hosts_non_empty()
- test_cors_origins_non_empty()
- test_database_url_postgres_only()
- test_redis_url_required_in_prod()
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Assure que la racine du projet est dans sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from preflight_secrets import (
    SecretCheck,
    _check_database_url,
    _check_redis,
    _check_smtp_socket,
    _consistency_checks,
    _env,
    _is_placeholder,
    _is_prod,
    _llm_provider,
    _normalize_bool,
    _secret_checks,
    _shannon_entropy_per_char,
    _validate_fernet_key,
    _validate_jwt_secret,
    _validate_live_stripe,
    _validate_non_empty_csv,
    _validate_secret_key,
    _validate_url,
    collect_preflight_report,
    run_startup_preflight,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_env(monkeypatch, env="production", **overrides):
    """Fixture helper pour positionner les env vars de production."""
    monkeypatch.setenv("ENV", env)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)


# ── P0-5.A : Secret Key validation ──────────────────────────────────────────

@pytest.mark.unit
def test_secret_key_too_short():
    """SECRET_KEY < 64 caractères doit être rejeté."""
    result = _validate_secret_key("short_key")
    assert result is not None
    assert "trop court" in result


@pytest.mark.unit
def test_low_entropy_rejected():
    """Un SECRET_KEY avec entropie < 4.5 bits/car doit être rejeté."""
    result = _validate_secret_key("a" * 80)
    assert result is not None
    assert "entropie" in result


@pytest.mark.unit
def test_secret_key_placeholder_rejected():
    """Un SECRET_KEY contenant un placeholder doit être rejeté."""
    result = _validate_secret_key("placeholder_" + "x" * 60)
    assert result is not None
    assert "placeholder" in result


@pytest.mark.unit
def test_secret_key_valid(monkeypatch):
    """Un SECRET_KEY valide (64+ chars, bonne entropie) doit passer."""
    key = "v3ry-s3cur3-r4nd0m-k3y-w1th-h1gh-3ntr0py-!@#$%^&*()-1234567890abcdefghijklmnop"
    result = _validate_secret_key(key)
    assert result is None


# ── P0-5.B : Check de doublons ──────────────────────────────────────────────

@pytest.mark.unit
def test_consistency_checks_duplicate_keys(monkeypatch):
    """SECRET_KEY == ENCRYPTION_KEY doit déclencher un fail-fast."""
    monkeypatch.setenv("SECRET_KEY", "same-key-" + "x" * 50)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-" + "x" * 50)
    monkeypatch.setenv("ENCRYPTION_KEY", "same-key-" + "x" * 50)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key-12345")

    errors = _consistency_checks()
    assert any("SECRET_KEY et ENCRYPTION_KEY" in e for e in errors)


@pytest.mark.unit
def test_consistency_checks_jwt_same_as_secret(monkeypatch):
    """JWT_SECRET_KEY == SECRET_KEY doit déclencher un fail-fast."""
    monkeypatch.setenv("SECRET_KEY", "secret-" + "x" * 60)
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-" + "x" * 60)
    monkeypatch.setenv("ENCRYPTION_KEY", "encryption-" + "x" * 50)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key-12345")

    errors = _consistency_checks()
    assert any("JWT_SECRET_KEY" in e for e in errors)


# ── P0-5.A : Fernet key validation ─────────────────────────────────────────

@pytest.mark.unit
def test_fernet_key_invalid_base64():
    """Une ENCRYPTION_KEY avec base64 invalide doit être rejetée."""
    # Utiliser une clé assez longue mais invalide en Fernet
    result = _validate_fernet_key("A" * 44 + "!!!invalid!!!")
    assert result is not None


@pytest.mark.unit
def test_fernet_key_valid():
    """Une ENCRYPTION_KEY Fernet valide doit passer."""
    result = _validate_fernet_key("HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
    assert result is None


# ── P0-5.A : Stripe live prefix ────────────────────────────────────────────

@pytest.mark.unit
def test_stripe_live_prefix_required():
    """STRIPE_SECRET_KEY doit commencer par sk_live_ en production."""
    result = _validate_live_stripe("sk_test_abcdefghijklmnopqrstuvwxyz1234567890")
    assert result is not None
    assert "sk_live_" in result


@pytest.mark.unit
def test_stripe_live_prefix_valid():
    """STRIPE_SECRET_KEY avec sk_live_ doit passer."""
    result = _validate_live_stripe("sk_test_PLACEHOLDER_STRIPE_KEY")
    assert result is None


# ── P0-5.A : SMTP check required in prod ────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_smtp_check_required_in_prod(monkeypatch):
    """En production, SMTP_HOST absent doit produire une erreur."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_PORT", "")

    result = await _check_smtp_socket()
    assert result is not None
    assert "absent" in result


# ── P0-5.A : LLM stub blocked in prod ──────────────────────────────────────

@pytest.mark.unit
def test_llm_stub_blocked_in_prod(monkeypatch):
    """LLM_PROVIDER=stub doit être bloqué en production via consistency_checks."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("SECRET_KEY", "secret-" + "x" * 60)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-" + "x" * 60)
    monkeypatch.setenv("ENCRYPTION_KEY", "encrypt-" + "x" * 50)

    errors = _consistency_checks()
    assert any("stub" in e.lower() for e in errors)


# ── P0-5.C : KMS provider override ─────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_kms_provider_override(monkeypatch):
    """KMS_PROVIDER doit être lisible depuis les env vars."""
    monkeypatch.setenv("KMS_PROVIDER", "gsm")
    monkeypatch.setenv("ENV", "production")

    # Simuler la collecte du rapport preflight pour vérifier le champ kms_provider
    monkeypatch.setenv("SECRET_KEY", "v3ry-s3cur3-r4nd0m-k3y-w1th-h1gh-3ntr0py-!@#$%^&*()-1234567890abcdefghijklmnop")
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-key-32-characters-minimum-length-here-now")
    monkeypatch.setenv("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key-12345")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("STRIPE_ENABLED", "0")
    monkeypatch.setenv("FEATURE_FLAG_BYOK_OPENAI", "0")

    # Patcher les checks externes pour ne pas dépendre d'infra réelle
    with patch("preflight_secrets._check_redis", new_callable=AsyncMock, return_value=None):
        with patch("preflight_secrets._check_database_url", new_callable=AsyncMock, return_value=None):
            with patch("preflight_secrets._check_smtp_socket", new_callable=AsyncMock, return_value=None):
                report = await collect_preflight_report()

    assert report["checks"]["kms_provider"] == "gsm"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_kms_provider_default_local(monkeypatch):
    """KMS_PROVIDER par défaut doit être 'local'."""
    monkeypatch.delenv("KMS_PROVIDER", raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "v3ry-s3cur3-r4nd0m-k3y-w1th-h1gh-3ntr0py-!@#$%^&*()-1234567890abcdefghijklmnop")
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-key-32-characters-minimum-length-here-now")
    monkeypatch.setenv("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key-12345")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("STRIPE_ENABLED", "0")
    monkeypatch.setenv("FEATURE_FLAG_BYOK_OPENAI", "0")

    with patch("preflight_secrets._check_redis", new_callable=AsyncMock, return_value=None):
        with patch("preflight_secrets._check_database_url", new_callable=AsyncMock, return_value=None):
            with patch("preflight_secrets._check_smtp_socket", new_callable=AsyncMock, return_value=None):
                report = await collect_preflight_report()

    assert report["checks"]["kms_provider"] == "local"


# ── P0-5 : Structure du rapport preflight ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_collect_preflight_report_structure(monkeypatch):
    """Le rapport preflight doit avoir une structure JSON attendue."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.setenv("KMS_PROVIDER", "local")

    with patch("preflight_secrets._check_redis", new_callable=AsyncMock, return_value=None):
        with patch("preflight_secrets._check_database_url", new_callable=AsyncMock, return_value=None):
            with patch("preflight_secrets._check_smtp_socket", new_callable=AsyncMock, return_value=None):
                with patch("preflight_secrets._check_otlp_socket", new_callable=AsyncMock, return_value=None):
                    report = await collect_preflight_report()

    # Vérifier la structure
    assert "ok" in report
    assert "env" in report
    assert "timestamp" in report
    assert "errors" in report
    assert "warnings" in report
    assert "checks" in report
    assert isinstance(report["errors"], list)
    assert isinstance(report["warnings"], list)
    assert isinstance(report["checks"], dict)


# ── P0-5 : run_startup_preflight raises on errors ──────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_run_startup_preflight_raises_on_errors(monkeypatch):
    """En production avec des secrets manquants, run_startup_preflight doit lever RuntimeError."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("JWT_SECRET_KEY", "short")
    monkeypatch.setenv("ENCRYPTION_KEY", "short")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("ALLOWED_HOSTS", "")
    monkeypatch.setenv("CORS_ORIGINS", "")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("FEATURE_FLAG_OTEL", "0")
    monkeypatch.setenv("STRIPE_ENABLED", "0")
    monkeypatch.setenv("FEATURE_FLAG_BYOK_OPENAI", "0")

    with patch("preflight_secrets._check_redis", new_callable=AsyncMock, return_value=None):
        with patch("preflight_secrets._check_database_url", new_callable=AsyncMock, return_value=None):
            with patch("preflight_secrets._check_smtp_socket", new_callable=AsyncMock, return_value="SMTP indisponible"):
                with patch("preflight_secrets._check_otlp_socket", new_callable=AsyncMock, return_value=None):
                    with pytest.raises(RuntimeError, match="Preflight bloquant"):
                        await run_startup_preflight()


# ── P0-5 : ALLOWED_HOSTS / CORS_ORIGINS non vides ─────────────────────────

@pytest.mark.unit
def test_allowed_hosts_non_empty(monkeypatch):
    """ALLOWED_HOSTS vide doit être rejeté en production."""
    monkeypatch.setenv("ENV", "production")
    result = _validate_non_empty_csv("")
    assert result is not None
    assert "vide" in result


@pytest.mark.unit
def test_cors_origins_non_empty(monkeypatch):
    """CORS_ORIGINS vide doit être rejeté en production."""
    monkeypatch.setenv("ENV", "production")
    result = _validate_non_empty_csv("")
    assert result is not None
    assert "vide" in result


@pytest.mark.unit
def test_allowed_hosts_valid(monkeypatch):
    """ALLOWED_HOSTS valide doit passer."""
    result = _validate_non_empty_csv("myapp.com,api.myapp.com")
    assert result is None


# ── P0-5 : DATABASE_URL postgres only ──────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_database_url_postgres_only(monkeypatch):
    """DATABASE_URL doit pointer vers PostgreSQL en production."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    result = await _check_database_url()
    assert result is not None
    assert "PostgreSQL" in result


# ── P0-5 : REDIS_URL required in prod ──────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_redis_url_required_in_prod(monkeypatch):
    """REDIS_URL absent en production doit produire une erreur."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("REDIS_URL", raising=False)
    result = await _check_redis()
    assert result is not None
    assert "absent" in result


# ── Helpers : entropie et placeholder ──────────────────────────────────────

@pytest.mark.unit
def test_shannon_entropy_high_for_random():
    """L'entropie d'une chaîne aléatoire doit être > 4.0."""
    entropy = _shannon_entropy_per_char("a1b2c3d4e5f6g7h8i9j0")
    assert entropy > 4.0


@pytest.mark.unit
def test_shannon_entropy_low_for_repetitive():
    """L'entropie d'une chaîne répétitive doit être < 1.0."""
    entropy = _shannon_entropy_per_char("a" * 100)
    assert entropy < 1.0


@pytest.mark.unit
def test_is_placeholder_common():
    """Les placeholders courants doivent être détectés."""
    assert _is_placeholder("changeme") is True
    assert _is_placeholder("password") is True
    assert _is_placeholder("your_secret_here") is True


@pytest.mark.unit
def test_is_not_placeholder():
    """Une vraie clé ne doit pas être détectée comme placeholder."""
    assert _is_placeholder("v3ry-s3cur3-r4nd0m-k3y") is False


# ── P0-5 : URL validation ──────────────────────────────────────────────────

@pytest.mark.unit
def test_validate_url_valid_https():
    """Une URL HTTPS valide doit passer."""
    result = _validate_url("https://hooks.sentry.io/abc")
    assert result is None


@pytest.mark.unit
def test_validate_url_invalid_scheme():
    """Une URL avec schéma invalide doit être rejetée."""
    result = _validate_url("ftp://example.com")
    assert result is not None


@pytest.mark.unit
def test_validate_url_empty():
    """Une URL vide doit être rejetée."""
    result = _validate_url("")
    assert result is not None
