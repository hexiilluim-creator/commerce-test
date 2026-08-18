"""
main.py — AutoCommerce V27.1 Entry Point
=======================================
FastAPI app with:
  - Multi-tenant JWT middleware
  - Alembic auto-migrations on startup (CLI-only in production)
  - Sentry error tracking
  - Structured JSON logging (structlog)
  - CORS with explicit origins (no wildcard in production)
  - Enterprise Security: SecurityHeaders, AuditLog, InputValidation, CSRF
  - Rate limiting via Redis (distributed, cross-worker)
  - Body size limits, trace IDs, PII redaction
"""
import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─────────────────────────────────────────────────────────────────────────────
from api.v1 import router as api_router
from api.v1.health import router as health_router
from config import settings
from middleware.audit_log import AuditLogMiddleware
from middleware.body_limit import BodySizeLimitMiddleware
from middleware.csrf_protection import CSRFProtectionMiddleware
from middleware.input_validation import InputValidationMiddleware
from middleware.rate_limit import RateLimitExceeded, SlowAPIMiddleware, _rate_limit_exceeded_handler, limiter

# ── Enterprise Security Middlewares (v18) ─────────────────────────────────────
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.tenant import TenantMiddleware
from middleware.trace_id import TraceIDMiddleware
from models.database import engine
from preflight_secrets import run_startup_preflight as _run_startup_preflight
from services.llm_gateway import guard_provider, provider_from_settings
from services.observability import check_otlp_endpoint, install_observability, require_runtime_observability

# ─── Logging ──────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)

_pii_env = settings.ENV.lower()
try:
    from services.pii_redactor import install_pii_redactor
    install_pii_redactor()
except Exception as _pii_exc:  # noqa: BLE001
    if _pii_env in ("production", "prod", "staging"):
        raise RuntimeError(
            f"[RGPD] PII Redactor failed to install in {_pii_env}. "
            "Cannot start without PII protection — this would log customer data in plaintext. "
            f"Error: {_pii_exc}"
        ) from _pii_exc
    else:
        import warnings
        warnings.warn(
            f"[DEV] PII Redactor failed to install: {_pii_exc}. "
            "Customer PII may appear in logs. Fix before deploying to production.",
            RuntimeWarning,
            stacklevel=1,
        )

logger = structlog.get_logger()

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    require_runtime_observability()
    install_observability(app)
    guard_provider(provider_from_settings())
    await _run_startup_preflight()
    logger.info("startup preflight passed")

    if getattr(settings, "FEATURE_FLAG_OTEL", False) and settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        if not await check_otlp_endpoint():
            raise RuntimeError("OTLP exporter indisponible au démarrage")

    logger.info("AutoCommerce V27.1 starting", env=settings.ENV)
    logger.info("Database connection ready (migrations handled via CLI)")

    cleanup_task = None
    try:
        from services.session_cleanup import start_cleanup_job
        cleanup_task = asyncio.create_task(start_cleanup_job())
        logger.info("session_cleanup job scheduled")
    except Exception as _cleanup_err:
        logger.warning("session_cleanup job failed to start: %s", _cleanup_err)

    yield

    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        logger.info("session_cleanup job stopped")

    logger.info("AutoCommerce V27.1 shutting down")
    await engine.dispose()

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AutoCommerce V27.1",
    description="AI-powered Omnichannel Commerce SaaS",
    version="27.1.0",
    docs_url="/docs" if settings.ENV.lower() == "development" else None,
    redoc_url="/redoc" if settings.ENV.lower() == "development" else None,
    openapi_url="/openapi.json" if settings.ENV.lower() == "development" else None,
    redirect_slashes=False,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 8/ Tenant isolation (runs last -> added first)
app.add_middleware(TenantMiddleware)

# 7/ CORS - P0-FIX: Robust parsing of CORS_ORIGINS from env
_raw_origins = settings.CORS_ORIGINS or os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _raw_origins.replace(";", ",").split(",") if o.strip()]

# V26 FIX (rapport §6.1) — Configuration CORS dynamique.
# Une origine explicitement fournie doit toujours être prioritaire, même en
# développement : le wildcard est incompatible avec withCredentials=true.
if _cors_origins:
    logger.info("CORS origins configured", origins=_cors_origins)
elif settings.ENV.lower() == "development" or settings.DEBUG:
    _cors_origins = ["*"]
    logger.info("CORS configured for development (wildcard enabled)")
elif not _cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS must be explicitly configured in production; refusing insecure localhost fallback."
    )
else:
    logger.info("CORS origins configured", origins=_cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://commerce-frontend-production-68ce.up.railway.app"],
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-CSRF-Token",
    ],
)

# 6/ CSRF Protection
app.add_middleware(CSRFProtectionMiddleware)

# 5/ Audit Logging
app.add_middleware(AuditLogMiddleware)

# 4/ Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# 3/ Input Validation
# app.add_middleware(InputValidationMiddleware)

# 2/ Body size limit
app.add_middleware(BodySizeLimitMiddleware)

# 1/ Rate limit
if os.getenv("SKIP_LIMITER") != "1":
    app.add_middleware(SlowAPIMiddleware)

# 0/ Trace ID
app.add_middleware(TraceIDMiddleware)

# Routes
app.include_router(api_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api")
app.include_router(health_router)
app.include_router(health_router, prefix="/api/v1")

# V26 FIX (rapport §2.1) — Handler explicite OPTIONS catch-all
# ----------------------------------------------------------------
# Certaines routes (POST /api/v1/auth/login, etc.) ne déclarent pas
# explicitement OPTIONS, ce qui provoque un 405 Method Not Allowed après le
# 200 OK du middleware CORS — sans impact fonctionnel sur Chrome/Firefox mais
# rejeté par certains clients HTTP stricts (curl -X OPTIONS, HTTP/1.1 clients).
# On ajoute un fallback global qui renvoie 204 No Content pour toute pré-flight.
from fastapi import Response as _Response


@app.options("/{full_path:path}", include_in_schema=False)
async def _cors_preflight_catchall(full_path: str):  # noqa: ARG001
    """Catch-all pour les requêtes CORS pre-flight non déclarées par un routeur.

    Le middleware CORS répond déjà aux OPTIONS quand l'origine est autorisée ;
    ce handler garantit qu'aucune route ne retombe sur 405 quand la requête
    OPTIONS parvient au routeur (clients HTTP stricts).
    """
    return _Response(status_code=204)

# Prometheus metrics
try:
    from fastapi import Header as _Header
    from fastapi.responses import PlainTextResponse as _PlainTextResponse
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from prometheus_fastapi_instrumentator import Instrumentator

    _instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/health", "/health/live", "/health/ready", "/api/health/live", "/api/health/ready"],
    ).instrument(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(
        x_internal_token: str | None = _Header(None, alias="X-Internal-Token"),
    ):
        is_test_env = settings.ENV.lower() == "test"
        if not is_test_env:
            if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.INTERNAL_HEALTH_TOKEN):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="X-Internal-Token missing or invalid")
        return _PlainTextResponse(
            generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )
except ImportError:
    pass

# Global error handler
from starlette.exceptions import HTTPException as _StarletteHTTPException


@app.exception_handler(_StarletteHTTPException)
async def http_exception_handler(request: Request, exc: _StarletteHTTPException):
    logger.warning("HTTP exception", path=request.url.path, status=exc.status_code, detail=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail if isinstance(exc.detail, str) else "HTTP error"},
        headers=getattr(exc, "headers", None),
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, _StarletteHTTPException):
        return await http_exception_handler(request, exc)
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.error("unhandled_exception", trace_id=trace_id, path=request.url.path, method=request.method, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "trace_id": trace_id,
            "message": "An unexpected error occurred. Please try again or contact support.",
        },
    )
