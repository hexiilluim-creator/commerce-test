#!/usr/bin/env python3
"""
preflight_check.py — AutoCommerce V25 startup validation
=========================================================
Validates all required environment variables before uvicorn starts.
Blocks launch and prints actionable errors when misconfiguration is detected.

Usage (automatic via start.sh):
    python preflight_check.py

Exit codes:
    0 — all checks passed, safe to start
    1 — one or more CRITICAL failures (blocks startup)

In ENV=development / DEBUG=true: warnings are printed but startup is NOT blocked.
In ENV=staging or ENV=production: any failure exits 1 and blocks uvicorn.
"""

from __future__ import annotations

import os
import sys

# ── Terminal colours (safe fallback if not a TTY) ───────────────────────────
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
RED    = "\033[0;31m" if _IS_TTY else ""
YELLOW = "\033[1;33m" if _IS_TTY else ""
GREEN  = "\033[0;32m" if _IS_TTY else ""
BLUE   = "\033[0;34m" if _IS_TTY else ""
BOLD   = "\033[1m"    if _IS_TTY else ""
RESET  = "\033[0m"    if _IS_TTY else ""

# ── Helpers ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

def _is_prod() -> bool:
    env = _env("ENV", "production").lower()
    debug = _env("DEBUG", "false").lower() in ("1", "true", "yes")
    return env in ("production", "staging") and not debug

def _is_placeholder(value: str, *placeholders: str) -> bool:
    v = value.lower()
    insecure = [
        "default", "placeholder",
        "replace_me", "replace_with", "todo", "fixme",
        "example", "test", "staging-secret", "your_secret_here",
        "none", "null",
    ]
    for p in (*insecure, *[x.lower() for x in placeholders]):
        if p in v:
            return True
    return False

# ── Check registry ───────────────────────────────────────────────────────────
# Each check returns (level, message) or None if passing.
# level: "CRITICAL" | "WARNING"

FAILURES: list[tuple[str, str]] = []

def _fail(level: str, var: str, message: str) -> None:
    FAILURES.append((level, f"{var}: {message}"))

# ── 1. DATABASE_URL ──────────────────────────────────────────────────────────
def check_database_url() -> None:
    v = _env("DATABASE_URL")
    if not v:
        _fail("CRITICAL", "DATABASE_URL", "Not set. Required. Example: postgresql+asyncpg://user:pass@host:5432/dbname")
        return
    if "sqlite" in v.lower() and _is_prod():
        _fail("CRITICAL", "DATABASE_URL", "SQLite is not supported in production. Use PostgreSQL.")

# ── 2. JWT_SECRET_KEY ────────────────────────────────────────────────────────
def check_jwt_secret() -> None:
    v = _env("JWT_SECRET_KEY")
    if not v:
        _fail("CRITICAL", "JWT_SECRET_KEY", "Not set. Generate with: openssl rand -hex 32")
        return
    if len(v) < 32:
        _fail("CRITICAL", "JWT_SECRET_KEY", f"Too short ({len(v)} chars). Minimum 32 characters required.")
    if _is_placeholder(v):
        _fail("CRITICAL", "JWT_SECRET_KEY", "Contains an insecure placeholder. Generate with: openssl rand -hex 32")

# ── 3. ENCRYPTION_KEY (Fernet) ───────────────────────────────────────────────
def check_encryption_key() -> None:
    v = _env("ENCRYPTION_KEY")
    if not v:
        _fail("CRITICAL", "ENCRYPTION_KEY",
              "Not set. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        return
    if _is_placeholder(v, "REPLACE_WITH_VALID_FERNET_KEY"):
        _fail("CRITICAL", "ENCRYPTION_KEY", "Contains an insecure placeholder. Generate a real Fernet key.")
        return
    try:
        from cryptography.fernet import Fernet
        Fernet(v.encode() if isinstance(v, str) else v)
    except Exception as exc:
        _fail("CRITICAL", "ENCRYPTION_KEY", f"Not a valid Fernet key: {exc}. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

# ── 4. CSRF_SECRET ───────────────────────────────────────────────────────────
def check_csrf_secret() -> None:
    v = _env("CSRF_SECRET")
    if not v and _is_prod():
        _fail("CRITICAL", "CSRF_SECRET",
              "Not set. In multi-worker production deployments, each worker generates a "
              "different random secret, making CSRF tokens cross-worker invalid. "
              "Generate with: openssl rand -hex 32")
    elif v and len(v) < 16:
        _fail("CRITICAL", "CSRF_SECRET", f"Too short ({len(v)} chars). Minimum 16 characters.")
    elif v and _is_placeholder(v):
        _fail("CRITICAL", "CSRF_SECRET", "Contains an insecure placeholder. Generate with: openssl rand -hex 32")

# ── 5. REDIS_URL ─────────────────────────────────────────────────────────────
def check_redis_url() -> None:
    v = _env("REDIS_URL", "redis://redis:6379/0")
    if not v:
        _fail("CRITICAL", "REDIS_URL", "Not set. Example: redis://localhost:6379/0")
    elif not (v.startswith("redis://") or v.startswith("rediss://") or v.startswith("redis-sentinel://")):
        _fail("WARNING", "REDIS_URL", f"Unexpected scheme in '{v}'. Expected redis://, rediss://, or redis-sentinel://")

# ── 6. INTERNAL_HEALTH_TOKEN ─────────────────────────────────────────────────
def check_health_token() -> None:
    v = _env("INTERNAL_HEALTH_TOKEN")
    if (not v or _is_placeholder(v)) and _is_prod():
        _fail("CRITICAL", "INTERNAL_HEALTH_TOKEN",
              "Still set to insecure default. Generate with: openssl rand -hex 32")

# ── 7. WhatsApp (production only) ────────────────────────────────────────────
def check_whatsapp() -> None:
    if not _is_prod():
        return
    secret = _env("WHATSAPP_APP_SECRET")
    if not secret:
        _fail("CRITICAL", "WHATSAPP_APP_SECRET",
              "Not set in production. Without HMAC verification, webhook payloads "
              "cannot be authenticated — any caller can forge WhatsApp events.")
    verify = _env("WHATSAPP_VERIFY_TOKEN")
    if not verify or _is_placeholder(verify):
        _fail("CRITICAL", "WHATSAPP_VERIFY_TOKEN", "Still set to insecure default. Set a strong random value.")

# ── 8. Social verify tokens (production only) ─────────────────────────────────
def check_social_tokens() -> None:
    if not _is_prod():
        return
    checks = [
        ("INSTAGRAM_VERIFY_TOKEN", ""),
        ("FACEBOOK_VERIFY_TOKEN", ""),
    ]
    for var, default in checks:
        v = _env(var, default)
        if not v or _is_placeholder(v):
            _fail("WARNING", var, "Still set to insecure default. Set a strong random value.")

# ── 9. CORS_ORIGINS ──────────────────────────────────────────────────────────
def check_cors() -> None:
    if not _is_prod():
        return
    origins = [o.strip() for o in _env("CORS_ORIGINS", "").split(",")]
    if "*" in origins:
        _fail("CRITICAL", "CORS_ORIGINS",
              "Wildcard '*' is set in production. This breaks HttpOnly cookies "
              "(withCredentials). Set explicit origins: https://app.example.com")

# ── 10. PORT ─────────────────────────────────────────────────────────────────
def check_port() -> None:
    port = _env("PORT", "8000")
    try:
        p = int(port)
        if not (1 <= p <= 65535):
            _fail("CRITICAL", "PORT", f"Invalid port number: {port}. Must be 1-65535.")
    except ValueError:
        _fail("CRITICAL", "PORT", f"Not a valid integer: {port!r}")

# ── 11. UVICORN_WORKERS ───────────────────────────────────────────────────────
def check_workers() -> None:
    w = _env("UVICORN_WORKERS", "4")
    try:
        n = int(w)
        if n < 1:
            _fail("CRITICAL", "UVICORN_WORKERS", "Must be >= 1")
        elif n > 32:
            _fail("WARNING", "UVICORN_WORKERS", f"{n} workers seems very high. Typical is 2-8.")
    except ValueError:
        _fail("CRITICAL", "UVICORN_WORKERS", f"Not a valid integer: {w!r}")

# ── 12. AI Keys (at least one required in production) ────────────────────────
def check_ai_keys() -> None:
    if not _is_prod():
        return
    openai = _env("OPENAI_API_KEY")
    deepseek = _env("DEEPSEEK_API_KEY")
    ds_enabled = _env("FEATURE_FLAG_DEEPSEEK", "true").lower() in ("1", "true", "yes")
    oa_fallback = _env("FEATURE_FLAG_OPENAI_FALLBACK", "true").lower() in ("1", "true", "yes")

    if not openai and not deepseek:
        _fail("CRITICAL", "OPENAI_API_KEY / DEEPSEEK_API_KEY",
              "At least one AI provider key must be set in production.")
    elif not openai and oa_fallback:
        _fail("WARNING", "OPENAI_API_KEY",
              "FEATURE_FLAG_OPENAI_FALLBACK=true but OPENAI_API_KEY is empty. "
              "Fallback will fail when DeepSeek is unavailable.")
    elif not deepseek and ds_enabled:
        _fail("WARNING", "DEEPSEEK_API_KEY",
              "FEATURE_FLAG_DEEPSEEK=true but DEEPSEEK_API_KEY is empty. "
              "Primary AI provider will fail — all traffic will hit the fallback.")

# ── Run all checks ────────────────────────────────────────────────────────────

def run_all() -> int:
    """Run all checks. Return exit code (0=OK, 1=critical failure)."""
    print(f"\n{BOLD}{BLUE}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{BLUE}║   AutoCommerce V25 — Preflight Environment Check          ║{RESET}")
    print(f"{BOLD}{BLUE}╚══════════════════════════════════════════════════════════╝{RESET}")
    env_name = _env("ENV", "production")
    prod = _is_prod()
    print(f"  ENV={env_name}  |  strict_mode={'YES (blocks startup)' if prod else 'NO (warnings only)'}\n")

    checks = [
        check_database_url,
        check_jwt_secret,
        check_encryption_key,
        check_csrf_secret,
        check_redis_url,
        check_health_token,
        check_whatsapp,
        check_social_tokens,
        check_cors,
        check_port,
        check_workers,
        check_ai_keys,
    ]

    for check in checks:
        check()

    # ── Report ────────────────────────────────────────────────────────────────
    criticals = [(l, m) for l, m in FAILURES if l == "CRITICAL"]
    warnings  = [(l, m) for l, m in FAILURES if l == "WARNING"]

    for _level, msg in warnings:
        print(f"  {YELLOW}⚠  WARNING{RESET}  {msg}")

    for _level, msg in criticals:
        print(f"  {RED}✗  CRITICAL{RESET} {msg}")

    if not FAILURES:
        print(f"  {GREEN}✓  All preflight checks passed.{RESET}")
    print()

    if criticals and prod:
        print(f"{RED}{BOLD}Startup BLOCKED: {len(criticals)} critical issue(s) found.{RESET}")
        print("Fix the issues above and restart.\n")
        return 1

    if criticals and not prod:
        print(f"{YELLOW}Development mode: {len(criticals)} critical issue(s) found but startup not blocked.{RESET}")
        print("These WILL block startup in production.\n")

    return 0


if __name__ == "__main__":
    sys.exit(run_all())
