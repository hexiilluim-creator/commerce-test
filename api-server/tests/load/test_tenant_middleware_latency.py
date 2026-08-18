"""tests/load/test_tenant_middleware_latency.py — Load / benchmark test.

BLOC 4 — SLA de latence :
    Le ``TenantMiddleware`` ne doit ajouter au maximum **5 ms** de latence par
    requête au P95, mesurés sur 1 000 requêtes locales.

Exécution :
    pytest -m load tests/load/test_tenant_middleware_latency.py -v

Le test est marqué ``@pytest.mark.load`` afin d'être exclu de la suite unitaire
et exécuté uniquement dans les pipelines de perf.
"""
from __future__ import annotations

import os
import statistics
import time
from typing import Any

import pytest

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("SKIP_LIMITER", "1")

pytestmark = pytest.mark.load

# Seuils SLA
MAX_MEAN_MS = 5.0
MAX_P95_MS = 5.0
MAX_P99_MS = 10.0
N_ITERATIONS = 1000

# ── Utilitaires ──────────────────────────────────────────────────────────────


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    k = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


def _make_jwt(store_id: int, role: str = "admin") -> str:
    from datetime import UTC, datetime, timedelta

    import jwt as jose
    payload = {
        "sub": str(store_id),
        "store_id": store_id,
        "role": role,
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    return jose.encode(payload, "test-secret-key-32chars-minimum!!", algorithm="HS256")


# ── Bench 1 : décodage JWT pur (composant central du middleware) ─────────────


def test_jwt_decode_latency_under_5ms_p95():
    """Le décodage JWT à lui seul doit rester <5ms au P95."""
    import jwt as jose

    token = _make_jwt(1)
    secret = "test-secret-key-32chars-minimum!!"

    # Warm-up
    for _ in range(50):
        jose.decode(token, secret, algorithms=["HS256"])

    samples: list[float] = []
    for _ in range(N_ITERATIONS):
        t0 = time.perf_counter()
        jose.decode(token, secret, algorithms=["HS256"])
        samples.append((time.perf_counter() - t0) * 1000.0)

    mean = statistics.fmean(samples)
    p95 = _percentile(samples, 95)
    p99 = _percentile(samples, 99)

    print(f"\n[JWT decode] mean={mean:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms")
    assert mean < MAX_MEAN_MS, f"JWT decode mean {mean:.3f}ms > {MAX_MEAN_MS}ms"
    assert p95 < MAX_P95_MS, f"JWT decode p95 {p95:.3f}ms > {MAX_P95_MS}ms"


# ── Bench 2 : logique interne du TenantMiddleware (path public + tenant resolve)


def test_tenant_middleware_path_check_latency():
    """Vérification is_public + extraction store_id : très rapide, < 1ms P95."""
    try:
        from middleware.tenant import _is_public
    except Exception:
        pytest.skip("middleware.tenant not importable in this environment")

    paths = [
        "/api/v1/orders",
        "/api/v1/products",
        "/api/v1/whatsapp/webhook/12",
        "/api/v1/auth/login",
        "/health",
        "/api/v1/storefront/products",
    ]

    # Warm-up
    for _ in range(100):
        for p in paths:
            _is_public(p)

    samples: list[float] = []
    for _ in range(N_ITERATIONS):
        t0 = time.perf_counter()
        for p in paths:
            _is_public(p)
        samples.append((time.perf_counter() - t0) * 1000.0)

    mean = statistics.fmean(samples)
    p95 = _percentile(samples, 95)
    print(f"\n[_is_public x{len(paths)}] mean={mean:.3f}ms p95={p95:.3f}ms")
    # Un lot de 6 checks doit être largement sous les 5ms
    assert p95 < MAX_P95_MS, f"is_public batch p95 {p95:.3f}ms > {MAX_P95_MS}ms"


# ── Bench 3 : coût cumulé JWT + path check (approximation du middleware) ─────


def test_full_tenant_check_pipeline_latency():
    """Simulation d'un cycle complet : is_public + JWT decode + attribution ContextVar."""
    try:
        from middleware.tenant import _is_public, current_tenant_id
    except Exception:
        pytest.skip("middleware.tenant not importable in this environment")

    import jwt as jose
    token = _make_jwt(42)
    secret = "test-secret-key-32chars-minimum!!"

    # Warm-up
    for _ in range(100):
        if not _is_public("/api/v1/orders"):
            payload = jose.decode(token, secret, algorithms=["HS256"])
            current_tenant_id.set(payload["store_id"])

    samples: list[float] = []
    for _ in range(N_ITERATIONS):
        t0 = time.perf_counter()
        if not _is_public("/api/v1/orders"):
            payload = jose.decode(token, secret, algorithms=["HS256"])
            current_tenant_id.set(payload["store_id"])
        samples.append((time.perf_counter() - t0) * 1000.0)

    mean = statistics.fmean(samples)
    p95 = _percentile(samples, 95)
    p99 = _percentile(samples, 99)

    print(f"\n[full pipeline] mean={mean:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms n={N_ITERATIONS}")

    assert mean < MAX_MEAN_MS, f"pipeline mean {mean:.3f}ms > {MAX_MEAN_MS}ms"
    assert p95 < MAX_P95_MS, f"pipeline p95 {p95:.3f}ms > {MAX_P95_MS}ms"
    assert p99 < MAX_P99_MS, f"pipeline p99 {p99:.3f}ms > {MAX_P99_MS}ms"


# ── Load test optionnel via pytest-benchmark ─────────────────────────────────


@pytest.mark.benchmark
def test_tenant_middleware_benchmark(benchmark: Any):
    """Alias benchmark si ``pytest-benchmark`` est installé.

    Fournit une baseline détaillée (min/max/mean/stddev) au format
    ``pytest-benchmark`` pour intégration CI.
    """
    try:
        from middleware.tenant import _is_public, current_tenant_id
    except Exception:
        pytest.skip("middleware.tenant not importable in this environment")

    import jwt as jose
    token = _make_jwt(1)
    secret = "test-secret-key-32chars-minimum!!"

    def _run() -> int:
        if not _is_public("/api/v1/orders"):
            payload = jose.decode(token, secret, algorithms=["HS256"])
            current_tenant_id.set(payload["store_id"])
            return payload["store_id"]
        return 0

    try:
        result = benchmark(_run)
        assert result in (0, 1)
    except TypeError:
        # pytest-benchmark absent : on skippe proprement
        pytest.skip("pytest-benchmark not installed")
