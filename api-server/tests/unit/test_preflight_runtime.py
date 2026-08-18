import importlib

import pytest


@pytest.fixture
def preflight(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DEBUG", "false")
    import preflight_check
    module = importlib.reload(preflight_check)
    module.FAILURES.clear()
    return module


def test_helpers_and_placeholder_detection(preflight, monkeypatch):
    monkeypatch.setenv("VALUE", "  abc  ")
    assert preflight._env("VALUE") == "abc"
    assert preflight._env("MISSING", "fallback") == "fallback"
    assert preflight._is_prod() is True
    assert preflight._is_placeholder("replace_me_secret") is True
    assert preflight._is_placeholder("strong-value", "strong-value") is True


def test_database_jwt_encryption_and_csrf_failures(preflight, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    preflight.check_database_url()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x")
    preflight.check_database_url()
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    preflight.check_jwt_secret()
    monkeypatch.setenv("JWT_SECRET_KEY", "short")
    preflight.check_jwt_secret()
    monkeypatch.setenv("JWT_SECRET_KEY", "replace_me_" + "x" * 40)
    preflight.check_jwt_secret()
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    preflight.check_encryption_key()
    monkeypatch.setenv("ENCRYPTION_KEY", "invalid")
    preflight.check_encryption_key()
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    preflight.check_csrf_secret()
    assert len(preflight.FAILURES) >= 8


def test_redis_health_whatsapp_social_cors_failures(preflight, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "http://redis")
    preflight.check_redis_url()
    monkeypatch.delenv("INTERNAL_HEALTH_TOKEN", raising=False)
    preflight.check_health_token()
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "default-token")
    preflight.check_whatsapp()
    monkeypatch.delenv("INSTAGRAM_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("FACEBOOK_VERIFY_TOKEN", raising=False)
    preflight.check_social_tokens()
    monkeypatch.setenv("CORS_ORIGINS", "*")
    preflight.check_cors()
    assert any(var == "REDIS_URL" for _, msg in preflight.FAILURES for var in [msg.split(":", 1)[0]])
    assert any("CORS_ORIGINS" in msg for _, msg in preflight.FAILURES)


def test_port_workers_and_ai_key_branches(preflight, monkeypatch):
    monkeypatch.setenv("PORT", "0")
    preflight.check_port()
    monkeypatch.setenv("PORT", "not-int")
    preflight.check_port()
    monkeypatch.setenv("UVICORN_WORKERS", "0")
    preflight.check_workers()
    monkeypatch.setenv("UVICORN_WORKERS", "bad")
    preflight.check_workers()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    preflight.check_ai_keys()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek")
    preflight.check_ai_keys()
    assert any("PORT" in msg for _, msg in preflight.FAILURES)
    assert any("AI provider" in msg for _, msg in preflight.FAILURES)


def test_development_mode_warns_or_skips_strict_checks(preflight, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("CSRF_SECRET", "development-csrf-secret-1234")
    preflight.FAILURES.clear()
    assert preflight._is_prod() is False
    preflight.check_csrf_secret()
    preflight.check_health_token()
    preflight.check_whatsapp()
    preflight.check_social_tokens()
    preflight.check_cors()
    preflight.check_ai_keys()
    assert preflight.FAILURES == []


def test_run_all_returns_critical_failure_and_success(preflight, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    preflight.FAILURES.clear()
    assert preflight.run_all() == 1
    assert "CRITICAL" in capsys.readouterr().out
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("CSRF_SECRET", "development-csrf-secret-1234")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("UVICORN_WORKERS", "2")
    preflight.FAILURES.clear()
    assert preflight.run_all() == 0
    assert "All preflight checks passed" in capsys.readouterr().out
