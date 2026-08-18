import os
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


def _resolve_env_file() -> str:
    explicit_env_file = os.getenv("ENV_FILE")
    if explicit_env_file:
        explicit_path = Path(explicit_env_file)
        if not explicit_path.is_absolute():
            explicit_path = BASE_DIR / explicit_path
        return str(explicit_path)

    env_name = os.getenv("ENV", "development").strip().lower()
    environment_specific = BASE_DIR / f".env.{env_name}"
    default_env = BASE_DIR / ".env"

    if environment_specific.exists():
        return str(environment_specific)
    return str(default_env)


class Settings(BaseSettings):
    # App
    ENV: str = "production"
    DEBUG: bool = False
    SERVER_DOMAIN: str = "https://api.example.com"
    CORS_ORIGINS: str = ""

    # Database
    DATABASE_URL: str

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def ensure_asyncpg_url(cls, v: str) -> str:
        """Auto-convert postgresql:// / postgres:// to postgresql+asyncpg:// for async SQLAlchemy."""
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = "postgresql+asyncpg://" + v[len("postgres://"):]
            elif v.startswith("postgresql://"):
                v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    # C5 FIX: Separate Redis DBs prevent cache eviction from affecting rate limits and locks.
    # DB 0 = main data (sessions, dedup, Celery broker)
    # DB 1 = rate limiting (slowapi, tenant quotas) — safe to flush without data loss
    # DB 2 = cache (tenant state, store resolver) — ephemeral, auto-regenerated
    # Override each independently in prod: REDIS_RATELIMIT_URL=redis://redis:6379/1
    REDIS_RATELIMIT_URL: str = ""   # empty = use REDIS_URL DB 0 (backward compat)
    REDIS_CACHE_URL: str = ""       # empty = use REDIS_URL DB 0 (backward compat)

    # JWT
    JWT_SECRET_KEY: str

    # AUDIT FIX : rotation multi-clé pour JWT_SECRET_KEY, même pattern que
    # FERNET_KEYS_JSON ci-dessous. Avant ce fix, JWT_SECRET_KEY était une
    # valeur statique unique — la roter invalidait 100% des sessions actives
    # instantanément, sans fenêtre de recouvrement. JSON array de clés
    # (newest first) — JWT_SECRET_KEY signe les nouveaux tokens, TOUTES les
    # clés de cette liste + JWT_SECRET_KEY sont essayées à la vérification.
    # Vide = comportement legacy (JWT_SECRET_KEY seul).
    # Ex: JWT_SECRET_KEYS_JSON='["ancienne_cle_encore_valide_pour_transition"]'
    # Procédure de rotation : ajouter l'ancienne clé ici, changer
    # JWT_SECRET_KEY pour la nouvelle, laisser tourner le temps que tous les
    # tokens signés avec l'ancienne clé expirent, puis vider cette liste.
    JWT_SECRET_KEYS_JSON: str = ""

    # Encryption
    ENCRYPTION_KEY: str

    # HIGH-8 FIX: Rotation multi-clé Fernet via FERNET_KEYS_JSON.
    # JSON array de clés Fernet (newest first) — la PREMIÈRE chiffre les nouvelles données,
    # TOUTES sont essayées au déchiffrement. Vide = utilise ENCRYPTION_KEY seul (mode legacy).
    # Ex: FERNET_KEYS_JSON='["nouvelle_cle=", "ancienne_cle="]'
    # Voir services/fernet_rotation.py pour la procédure complète.
    FERNET_KEYS_JSON: str = ""

    # CSRF Protection — double-submit cookie pattern
    # Generate with: openssl rand -hex 32
    CSRF_SECRET: str = ""  # P0-FIX: was read via os.getenv() in csrf_protection.py, bypassing pydantic validation

    @field_validator("CSRF_SECRET")
    @classmethod
    def validate_csrf_secret(cls, v: str, info: "ValidationInfo") -> str:
        # L2-FIX: reject empty CSRF_SECRET in production — without it the server
        # falls back to a random per-process key (csrf_protection.py:RuntimeWarning)
        # causing every cross-worker CSRF check to fail on multi-worker deployments.
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        if not v.strip() and env == "production" and not debug:
            raise ValueError(
                "CSRF_SECRET must be set in production. "
                "Generate with: openssl rand -hex 32"
            )
        return v

    # WhatsApp
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    # Instagram (social webhooks BYOK)
    INSTAGRAM_VERIFY_TOKEN: str = ""
    INSTAGRAM_APP_SECRET: str = ""

    # Facebook (social webhooks BYOK)
    FACEBOOK_VERIFY_TOKEN: str = ""
    FACEBOOK_APP_SECRET: str = ""

    # TikTok (social webhooks BYOK)
    TIKTOK_APP_SECRET: str = ""
    TIKTOK_VERIFY_TOKEN: str = ""
    TIKTOK_ENABLED: bool = False
    TIKTOK_ALLOW_REAL_CALLS: bool = False

    # ── CRIT-3 FIX: Validators pour tous les verify tokens webhook ─────────
    # Les tokens WhatsApp/Meta/TikTok n'avaient AUCUNE validation Pydantic
    # contrairement à INTERNAL_HEALTH_TOKEN. Un token par défaut non configuré en production
    # permet à n'importe qui d'envoyer de faux webhooks Meta -> commandes fantômes.
    # Correction: même stratégie que validate_health_token, appliquée sur les 4 tokens.
    @field_validator(
        "WHATSAPP_VERIFY_TOKEN",
        "INSTAGRAM_VERIFY_TOKEN",
        "FACEBOOK_VERIFY_TOKEN",
        "TIKTOK_VERIFY_TOKEN",
        mode="before",
    )
    @classmethod
    def validate_webhook_verify_tokens(cls, v: str, info: "ValidationInfo") -> str:
        """CRIT-3 FIX: Rejette les valeurs par défaut non configurées en production.

        En développement (ENV=development ou DEBUG=True) les valeurs par défaut
        sont autorisées pour ne pas bloquer les developers qui n'ont pas encore
        configuré les webhooks Meta.

        En production / staging: l'application refuse de démarrer si un des
        4 verify tokens est encore à sa valeur d'usine, évitant l'injection
        de faux webhooks WhatsApp/Instagram/Facebook/TikTok.
        """
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        is_prod = env.lower() in ("production", "prod", "staging") and not debug
        if is_prod and isinstance(v, str) and not v.strip():
            field_name = info.field_name if info.field_name else "VERIFY_TOKEN"
            raise ValueError(
                f"{field_name} must be changed from its default value in production. "
                "Current value is empty or unset. "
                f"Generate a strong random value: openssl rand -hex 24"
            )
        return v

    # ACTION 4: Alertes proactives émotions critiques
    SLACK_ALERT_WEBHOOK: str = ""
    EMOTION_ESCALATION_THRESHOLD: int = 2

    # OmniCall V9 Feature Flags
    OMNICALL_V9_SHADOW_MODE: str = "0"
    OMNICALL_V9_ENABLED: str = "0"
    OMNICALL_V9_ROLLOUT_PCT: str = "0"
    OMNICALL_V9_BETA_STORES: str = ""

    # Internal health token (protège /health/detailed)
    INTERNAL_HEALTH_TOKEN: str = ""
    # Internal API key for admin routes and service-to-service auth
    INTERNAL_API_KEY: str = ""

    @field_validator("INTERNAL_HEALTH_TOKEN")
    @classmethod
    def validate_health_token(cls, v: str, info: "ValidationInfo") -> str:
        # C9 FIX: reject the insecure default in production
        # In dev/test (DEBUG=True or ENV=development) the default is allowed
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        if not v.strip() and env == "production" and not debug:
            raise ValueError(
                "INTERNAL_HEALTH_TOKEN must be changed from default value in production. "
                "Generate with: openssl rand -hex 32"
            )
        return v

    # ── Providers IA — Architecture plateforme (v18.1) ──────────────────────
    # DeepSeek = provider PRIMAIRE (moins cher, ~10x vs GPT-4o)
    # OpenAI gpt-4o-mini = FALLBACK automatique si DeepSeek échoue
    # BYOK désactivé — tous les tenants partagent les clés plateforme.
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    FEATURE_FLAG_DEEPSEEK: bool = True
    FEATURE_FLAG_OPENAI_FALLBACK: bool = True

    # OpenAI fallback — utiliser gpt-4o-mini (rapport qualité/prix optimal)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"         # fallback standard
    OPENAI_VISION_MODEL: str = "gpt-4o"       # vision : garder 4o (multimodal supérieur)
    OPENAI_LOW_COST_MODEL: str = "gpt-4o-mini" 

    # SaaS / FinOps overlay
    AI_BUDGET_HARD_LIMIT_USD: float = 250.0
    AI_MAX_MONTHLY_CALLS: int = 10000
    AI_MAX_MONTHLY_TOKENS: int = 2000000
    AI_WARNING_THRESHOLD_PCT: int = 80
    AI_DEGRADED_THRESHOLD_PCT: int = 100
    AI_CONTROLLED_FALLBACK_MESSAGE: str = "Service IA momentanément limité pour ce tenant. Merci de réessayer plus tard."
    SAAS_BILLING_WEBHOOK_SECRET: str = ""

    # ── Sécurité inputs IA ────────────────────────────────────────────────────
    # HIGH-11 FIX: Limite universelle de taille des inputs texte envoyés au LLM.
    # Appliquée dans whatsapp.py (webhook), ai.py (search, spending insight).
    # La valeur du guardrail optionnel dans ai_guardrails.py est cohérente avec cette valeur.
    MAX_INPUT_LENGTH: int = 2000  # caractères — longueur max d'un message commercial raisonnable

    # HIGH-3 FIX: TTL explicite pour les tokens de réinitialisation de mot de passe.
    # Standard de sécurité OWASP: 15 minutes maximum.
    # Documenté dans .env.example pour les déploiements.
    RESET_TOKEN_TTL: int = 900  # secondes (15 min) — override via .env si besoin

    # Runtime tuning — V18 enterprise 2000+ tenants
    PORT: int = 8000
    # V18 2k-FIX: default 8 workers (was 4) — 2×vCPU minimum on production pods.
    # For 2000+ tenants at peak: deploy 3+ pods (3 × 8 workers = 24 Uvicorn workers).
    # Single pod with 8 workers handles ~800 req/s on a 4-vCPU VM.
    UVICORN_WORKERS: int = 4  # FIX: was 8 — règle 2×vCPU. Pour 4 vCPU -> 9 workers. Ajuster via env UVICORN_WORKERS.

    # V18 2k-FIX: DB pool tuning for 2000+ tenants
    # With PgBouncer (transaction mode): DB_POOL_SIZE=5 — PgBouncer multiplexes
    # With direct PostgreSQL (no PgBouncer): DB_POOL_SIZE=15
    # PgBouncer is set to max_client_conn=2000, default_pool_size=100 in docker-compose.ha.yml
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 3
    # V18 2k-FIX: statement timeout prevents long-running queries from starving the pool
    # Set to 0 to disable (not recommended in multi-tenant environments)
    DB_STATEMENT_TIMEOUT_MS: int = 30000  # 30 seconds

    # V18 2k-FIX: Redis connection pool sizing for 2000+ tenants
    # Each uvicorn worker opens up to REDIS_MAX_CONNECTIONS connections.
    # Total Redis connections = pods × workers × REDIS_MAX_CONNECTIONS
    # Example: 3 pods × 8 workers × 10 = 240 connections to Redis master
    REDIS_MAX_CONNECTIONS: int = 10
    REDIS_SOCKET_TIMEOUT: float = 5.0
    REDIS_SOCKET_CONNECT_TIMEOUT: float = 3.0

    # Sentry / observabilité
    SENTRY_DSN: str | None = None
    FEATURE_FLAG_SENTRY: bool = True
    FEATURE_FLAG_OTEL: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "autocommerce"
    OTEL_EXPORTER_TIMEOUT_SECONDS: float = 3.0
    HSTS_ENABLED: bool = True

    # Réseau applicatif
    ALLOWED_HOSTS: str = ""

    # SMTP transactionnel
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@autocommerce.ai"
    SMTP_USE_TLS: bool = True

    # LLM / guardrails provider
    LLM_PROVIDER: str = "deepseek"
    FEATURE_FLAG_BYOK_OPENAI: bool = False
    STORE_OPENAI_KEY: str = ""

    # Rotation JWT / secrets
    JWT_ROTATION_INTERVAL_HOURS: int = 24
    KMS_PROVIDER: str = "local"
    SECRET_KEY: str = ""
    PROMETHEUS_INTERNAL_TOKEN: str = ""

    # PSP sandbox / injection URLs
    FLOUCI_BASE_URL: str = ""
    KONNECT_BASE_URL: str = ""
    PAYMEE_BASE_URL: str = ""
    STRIPE_MOCK_BASE_URL: str = ""
    MOCK_PSP: bool = False

    # ── HARDENING SPRINT (BLOC 1 — Celery resilience) ─────────────────────
    CELERY_SOFT_TIME_LIMIT: int = 120        # seconds — raises SoftTimeLimitExceeded
    CELERY_TIME_LIMIT: int = 300             # seconds — worker SIGKILL
    CELERY_MAX_TASKS_PER_CHILD: int = 200
    CELERY_MAX_MEMORY_KB: int = 400_000      # 400 MB per worker child
    CELERY_BROKER_POOL_LIMIT: int = 10

    # ── HARDENING SPRINT (BLOC 2 — Distributed rate limit) ────────────────
    RL_LOGIN_LIMIT: int = 10                 # hits per RL_LOGIN_WINDOW seconds
    RL_LOGIN_WINDOW: int = 60
    RL_REGISTER_LIMIT: int = 5
    RL_REGISTER_WINDOW: int = 60
    RL_FORGOT_LIMIT: int = 5
    RL_FORGOT_WINDOW: int = 3600
    RL_AI_LIMIT: int = 60                    # per tenant per window
    RL_AI_WINDOW: int = 60
    RL_UPLOAD_LIMIT: int = 30                # per tenant per minute
    RL_UPLOAD_WINDOW: int = 60
    RL_WEBHOOK_LIMIT: int = 600              # per source IP per minute
    RL_WEBHOOK_WINDOW: int = 60

    # ── HARDENING SPRINT (BLOC 1.5 — Circuit breakers) ───────────────────
    CB_OPENAI_THRESHOLD: int = 6
    CB_OPENAI_COOLDOWN: int = 45
    CB_STRIPE_THRESHOLD: int = 5
    CB_STRIPE_COOLDOWN: int = 30

    # ── Facturation abonnement SaaS (marchand → AutoCommerce) ─────────────
    # AUDIT FIX : STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET étaient lus via
    # getattr(settings, "STRIPE_SECRET_KEY", "") dans services/saas_billing.py
    # sans jamais être déclarés comme champs Settings — avec
    # model_config(extra="ignore"), ces variables d'environnement étaient
    # donc TOUJOURS ignorées silencieusement, quelle que soit leur valeur
    # réelle dans .env. Le checkout Stripe abonnement ne pouvait jamais
    # fonctionner (ValueError "STRIPE_SECRET_KEY non configuré" systématique).
    # Marché Europe.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Flouci — marché Tunisie/local, compte marchand AutoCommerce (distinct
    # du BYOK par boutique utilisé pour les paiements de commandes clients,
    # voir services/payment_factory.py:FlouciProvider).
    FLOUCI_APP_TOKEN: str = ""
    FLOUCI_APP_SECRET: str = ""
    FLOUCI_WEBHOOK_SECRET: str = ""

    # ── HARDENING SPRINT (BLOC 2.3 — Uploads) ───────────────────────────
    UPLOAD_MAX_BYTES_IMAGE: int = 5 * 1024 * 1024    # 5 MB
    UPLOAD_MAX_BYTES_DOCUMENT: int = 10 * 1024 * 1024
    UPLOAD_STORAGE_ROOT: str = "uploads"              # base dir (rel. to backend/)
    # ── S3 / MinIO Object Storage (BLOCANT #4 FIX) ───────────────────────
    # Vide = fallback filesystem local (dev/CI). En production, toujours renseigner.
    S3_ENDPOINT: str = ""                     # ex: http://minio:9000 ou https://s3.amazonaws.com
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "autocommerce-uploads"
    S3_REGION: str = "us-east-1"
    S3_USE_PRESIGNED_URLS: bool = True
    S3_PRESIGNED_EXPIRY: int = 3600           # secondes
    S3_PUBLIC_URL: str = ""                   # URL CDN (optionnel)

    # ── Redis HA Sentinel (BLOCANT #2 FIX) ───────────────────────────────
    REDIS_SENTINEL_MASTER: str = "mymaster"
    REDIS_SENTINEL_PASSWORD: str = ""
    REDIS_PASSWORD: str = ""  # FIX: referenced in redis_lock.py Sentinel setup

    # ── PostgreSQL HA (BLOCANT #3 FIX) ──────────────────────────────────
    POSTGRES_REPLICATION_PASSWORD: str = ""


    # ── HARDENING SPRINT (BLOC 4 — Observability) ───────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"                 # json | text
    METRICS_ENABLED: bool = True

    # `extra="ignore"` lets ops set additional env vars (SKIP_LIMITER, OTLP_*, ...)
    # without crashing the process. The strict-typed fields above remain enforced.
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


    @field_validator("WHATSAPP_VERIFY_TOKEN")
    @classmethod
    def validate_whatsapp_verify_token(cls, v: str, info: "ValidationInfo") -> str:
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        if not v.strip() and env in ("production", "prod", "staging") and not debug:
            raise ValueError(
                "WHATSAPP_VERIFY_TOKEN must be changed from default in production. "
                "Set a strong random value: openssl rand -hex 32"
            )
        return v

    @field_validator("INSTAGRAM_VERIFY_TOKEN")
    @classmethod
    def validate_instagram_verify_token(cls, v: str, info: "ValidationInfo") -> str:
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        if not v.strip() and env in ("production", "prod", "staging") and not debug:
            raise ValueError(
                "INSTAGRAM_VERIFY_TOKEN must be changed from default in production."
            )
        return v

    @field_validator("FACEBOOK_VERIFY_TOKEN")
    @classmethod
    def validate_facebook_verify_token(cls, v: str, info: "ValidationInfo") -> str:
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        if not v.strip() and env in ("production", "prod", "staging") and not debug:
            raise ValueError(
                "FACEBOOK_VERIFY_TOKEN must be changed from default in production."
            )
        return v

    @field_validator("TIKTOK_VERIFY_TOKEN")
    @classmethod
    def validate_tiktok_verify_token(cls, v: str, info: "ValidationInfo") -> str:
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        enabled = (info.data or {}).get("TIKTOK_ENABLED", False)
        if enabled and not v.strip() and env in ("production", "prod", "staging") and not debug:
            raise ValueError(
                "TIKTOK_VERIFY_TOKEN must be changed from default when TIKTOK_ENABLED=True in production."
            )
        return v

    @field_validator("S3_SECRET_KEY")
    @classmethod
    def validate_s3_secret(cls, v: str, info: "ValidationInfo") -> str:
        env = (info.data or {}).get("ENV", "production")
        debug = (info.data or {}).get("DEBUG", False)
        endpoint = (info.data or {}).get("S3_ENDPOINT", "")
        if endpoint and not v and env == "production" and not debug:
            raise ValueError(
                "S3_SECRET_KEY est requis quand S3_ENDPOINT est défini en production."
            )
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        env = os.getenv("ENV", "production")
        if env.lower() == "production":
            origins = [o.strip() for o in v.split(",") if o.strip()]
            if not origins:
                raise ValueError(
                    "CORS_ORIGINS must be explicitly configured in production."
                )
            if "*" in origins:
                raise ValueError(
                    "CORS_ORIGINS cannot be '*' in production — "
                    "this breaks HttpOnly cookies (withCredentials). "
                    "Set explicit origins e.g. https://app.example.com"
                )
            if any("localhost" in origin.lower() for origin in origins):
                raise ValueError(
                    "CORS_ORIGINS cannot contain localhost in production. Set the real frontend origin(s)."
                )
        return v

    @field_validator("SERVER_DOMAIN")
    @classmethod
    def validate_server_domain(cls, v: str) -> str:
        env = os.getenv("ENV", "production")
        if env.lower() == "production":
            candidate = (v or "").strip().lower()
            if not candidate:
                raise ValueError("SERVER_DOMAIN must be set in production.")
            if "localhost" in candidate or candidate.endswith(".example") or candidate.endswith("example.com"):
                raise ValueError(
                    "SERVER_DOMAIN must point to the real public API domain in production."
                )
        return v

    @field_validator("WHATSAPP_APP_SECRET")
    @classmethod
    def validate_whatsapp_secret(cls, v: str) -> str:
        if os.getenv("ENV", "production").lower() == "production" and not v:
            raise ValueError(
                "WHATSAPP_APP_SECRET is required in production — "
                "without it, HMAC webhook verification is bypassed."
            )
        return v

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        try:
            Fernet(v.encode() if isinstance(v, str) else v)
        except Exception as exc:
            raise ValueError(
                "ENCRYPTION_KEY must be a valid Fernet key. "
                "Run: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from exc
        return v

    def get_fernet(self):
        """HIGH-8 FIX: MultiFernet si FERNET_KEYS_JSON défini, sinon Fernet single key."""
        from services.fernet_rotation import get_fernet as _get_fernet
        return _get_fernet()

    def encrypt(self, value: str, context: str | None = None) -> str:
        """Chiffre avec la clé active (première de FERNET_KEYS_JSON ou ENCRYPTION_KEY)."""
        from services.fernet_rotation import encrypt as _encrypt
        return _encrypt(value, context=context)

    def decrypt(self, value: str, context: str | None = None) -> str:
        """Déchiffre en essayant toutes les clés disponibles (rotation supportée)."""
        from services.fernet_rotation import decrypt as _decrypt
        return _decrypt(value, context=context)

    def encode_jwt(self, payload: dict, algorithm: str = "HS256") -> str:
        """Signe un JWT avec la clé active (JWT_SECRET_KEY)."""
        from services.jwt_rotation import encode_jwt as _encode_jwt
        return _encode_jwt(payload, algorithm=algorithm)

    def decode_jwt(self, token: str, algorithms: list[str] | None = None) -> dict:
        """Vérifie un JWT en essayant JWT_SECRET_KEY puis JWT_SECRET_KEYS_JSON (rotation)."""
        from services.jwt_rotation import decode_jwt as _decode_jwt
        return _decode_jwt(token, algorithms=algorithms)


settings = Settings()
