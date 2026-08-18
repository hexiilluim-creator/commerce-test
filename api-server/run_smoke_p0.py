"""Smoke tests for BLOCK P0."""
import asyncio
import json
import os
import sys
import traceback

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("SKIP_LIMITER", "1")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_wa_verify")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test_ig_verify")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test_fb_verify")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test_tt_verify")
sys.path.insert(0, os.path.dirname(__file__))

results = {"boot": False, "routes": 0, "tests": [], "errors": []}

def record(name, ok, detail=""):
    results["tests"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"  {'OK' if ok else 'FAIL'} {name}: {detail}")

print("\n=== STEP 1: Boot app ===")
try:
    from main import app
    results["boot"] = True
    results["routes"] = len(app.routes)
    record("app_import", True, f"{len(app.routes)} routes registered")
except Exception:
    record("app_import", False, traceback.format_exc())
    print(json.dumps(results, indent=2)); sys.exit(1)

print("\n=== STEP 2: Registered routes ===")
route_paths = []
for r in app.routes:
    p = getattr(r, "path", None)
    m = getattr(r, "methods", None)
    if p:
        route_paths.append((p, sorted(m or [])))

key_routes = [
    "/health",
    "/api/v1/whatsapp/webhook",
    "/api/v1/social/instagram/webhook",
    "/api/v1/social/facebook/webhook",
    "/api/v1/social/tiktok/webhook",
    "/api/v1/social/webhook",
    "/api/v1/appointments/",
    "/api/v1/appointments/services",
    "/api/v1/appointments/availability",
]
for kr in key_routes:
    found = any(p == kr or p.rstrip("/") == kr.rstrip("/") for p, _ in route_paths)
    record(f"route:{kr}", found, "registered" if found else "NOT FOUND")

print("\n=== STEP 3: HTTP smoke ===")
from fastapi.testclient import TestClient


async def init_db():
    from models.database import Base, engine
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

try:
    asyncio.run(init_db())
    record("db_schema_create", True, "tables created on sqlite")
except Exception as e:
    record("db_schema_create", False, str(e))

with TestClient(app) as client:
    r = client.get("/health")
    record("GET /health", r.status_code == 200, f"status={r.status_code}")

    r = client.get("/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "test_wa_verify", "hub.challenge": "12345"})
    record("GET /api/v1/whatsapp/webhook (verify)",
        r.status_code == 200 and r.text.strip('"') == "12345",
        f"status={r.status_code} body={r.text[:80]}")

    r = client.get("/api/v1/social/instagram/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "test_ig_verify", "hub.challenge": "abc"})
    record("GET /api/v1/social/instagram/webhook",
        r.status_code in (200, 403),
        f"status={r.status_code} body={r.text[:80]}")

    r = client.get("/api/v1/social/facebook/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "test_fb_verify", "hub.challenge": "abc"})
    record("GET /api/v1/social/facebook/webhook",
        r.status_code in (200, 403),
        f"status={r.status_code} body={r.text[:80]}")

    r = client.get("/api/v1/social/tiktok/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "test_tt_verify", "hub.challenge": "abc"})
    record("GET /api/v1/social/tiktok/webhook (disabled flag)",
        r.status_code in (200, 403, 503),
        f"status={r.status_code} body={r.text[:80]}")

    # Appointments — must respond with 401 (auth required), not 500
    for ep in ["/api/v1/appointments/", "/api/v1/appointments/services", "/api/v1/appointments/availability"]:
        r = client.get(ep)
        record(f"GET {ep} (auth required)", r.status_code == 401,
            f"status={r.status_code} (expected 401)")

total = len(results["tests"])
passed = sum(1 for t in results["tests"] if t["ok"])
results["summary"] = {"passed": passed, "total": total, "ok": passed == total}
print(f"\nSMOKE TEST P0: {passed}/{total} passed")
with open("SMOKE_P0_RESULTS.json", "w") as f:
    json.dump(results, f, indent=2)
sys.exit(0 if passed == total else 1)
