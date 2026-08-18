"""tests/test_preflight_smtp_conditional.py — preflight_secrets.py::run_preflight.

P1.12-FIX (audit externe, juillet 2026) : SMTP_HOST/USERNAME/PASSWORD
n'étaient qu'un avertissement non-bloquant, quelle que soit la
configuration. Corrigé : bloquant (sys.exit) si STRIPE_ENABLED=1, puisqu'un
marchand payant sans email transactionnel fonctionnel est un vrai problème
produit (mot de passe oublié, reçus de paiement). Reste non-bloquant pour
les déploiements sans Stripe.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from preflight_secrets import run_preflight

_BASE_REQUIRED_SECRETS = {
    "JWT_SECRET_KEY": "a" * 32,
    "ENCRYPTION_KEY": "ZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWU=",
    "CSRF_SECRET": "c" * 32,
    "PROMETHEUS_INTERNAL_TOKEN": "d" * 32,
    "POSTGRES_PASSWORD": "e" * 16,
    "REDIS_PASSWORD": "f" * 16,
    "ADMIN_INITIAL_PASSWORD": "g" * 12,
    "SUPERADMIN_INITIAL_PASSWORD": "h" * 12,
    "INTERNAL_HEALTH_TOKEN": "i" * 32,
    "INTERNAL_API_KEY": "j" * 32,
    "SECRET_KEY": "S3cret-Preflight!2026-Alpha#Q7x9Z2@M5v8K1p4R6t0-Delta$8N3w6Y1-FinalK9",
    "ALLOWED_HOSTS": "localhost",
    "CORS_ORIGINS": "http://localhost",
    "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/autocommerce",
    "REDIS_URL": "redis://localhost:6379/0",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Environnement minimal valide, sans Stripe ni SMTP configurés."""
    for key, value in _BASE_REQUIRED_SECRETS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("STRIPE_ENABLED", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("FEATURE_FLAG_SENTRY", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-" + "x" * 30)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    with patch("preflight_secrets._check_database_url", new=AsyncMock(return_value=None)), patch("preflight_secrets._check_redis", new=AsyncMock(return_value=None)), patch("preflight_secrets._check_smtp_socket", new=AsyncMock(return_value=None)):
        yield


def test_smtp_missing_without_stripe_does_not_block(clean_env):
    """Sans Stripe activé, SMTP manquant reste un avertissement — ne bloque pas."""
    run_preflight(env="production")  # ne doit pas lever SystemExit


def test_smtp_missing_with_stripe_enabled_blocks(clean_env, monkeypatch):
    """Stripe activé + SMTP manquant -> doit bloquer le démarrage."""
    monkeypatch.setenv("STRIPE_ENABLED", "1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" + "k" * 20)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_" + "m" * 20)

    with pytest.raises(SystemExit) as exc_info:
        run_preflight(env="production")
    assert exc_info.value.code == 1


def test_smtp_configured_with_stripe_enabled_passes(clean_env, monkeypatch):
    """Stripe activé + SMTP correctement configuré -> ne bloque pas."""
    monkeypatch.setenv("STRIPE_ENABLED", "1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" + "k" * 20)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_" + "m" * 20)
    monkeypatch.setenv("SMTP_HOST", "smtp.mailprovider-test-domain.net")
    monkeypatch.setenv("SMTP_USERNAME", "noreply@mailprovider-test-domain.net")
    monkeypatch.setenv("SMTP_PASSWORD", "n7q2vw84rtzupq1")

    run_preflight(env="production")  # ne doit pas lever SystemExit


def test_smtp_missing_in_dev_mode_never_blocks(clean_env, monkeypatch):
    """Même avec Stripe activé, le mode dev reste permissif (warnings seulement)."""
    monkeypatch.setenv("STRIPE_ENABLED", "1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" + "k" * 20)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_" + "m" * 20)

    run_preflight(env="development")  # ne doit pas lever SystemExit
