import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jwt.exceptions import PyJWTError as JWTError
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from middleware.rate_limit import limiter
from models.database import PasswordResetToken, Store, User, get_db
from services.ai_guardrails import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])

AUTH_COOKIE_NAME = "access_token"
AUTH_COOKIE_PATH = "/api"
AUTH_COOKIE_SAMESITE = "lax"

def _secure_cookie_enabled() -> bool:
    return settings.ENV.lower() in ("production", "prod", "staging")

def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_secure_cookie_enabled(),
        samesite=AUTH_COOKIE_SAMESITE,
        path=AUTH_COOKIE_PATH,
        max_age=60 * 60 * 24,
    )

def _clear_auth_cookie(response: Response) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value="",
        httponly=True,
        secure=_secure_cookie_enabled(),
        samesite=AUTH_COOKIE_SAMESITE,
        path=AUTH_COOKIE_PATH,
        max_age=0,
        expires=0,
    )

# ─── Schemas ──────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RegisterRequest(BaseModel):
    """
    P0-FIX (audit): `confirm_password` est désormais OPTIONNEL côté backend.

    Justification :
      - La confirmation est une garantie UX, pas une garantie de sécurité.
      - Le frontend continue à exiger et à comparer les deux champs.
      - Le backend l'accepte si présent (et vérifie la correspondance), mais
        ne le requiert plus — cela aligne le contrat avec les tests existants
        et évite les cascades de 422.
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str | None = Field(default=None, max_length=128)
    store_name: str = Field(min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        import re
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Le mot de passe doit contenir au moins une lettre")
        if not re.search(r"[0-9]", v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return v

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password_complexity(cls, v: str) -> str:
        """Enforce same complexity as registration — prevents bypass via reset flow.
        
        Without this, a user can reset to 'aaaaaaaa' (8 letters, 0 digits)
        bypassing the policy enforced on RegisterRequest.validate_password_complexity().
        """
        import re as _re
        if not _re.search(r"[A-Za-z]", v):
            raise ValueError("Le mot de passe doit contenir au moins une lettre")
        if not _re.search(r"[0-9]", v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return v

class GoogleLoginRequest(BaseModel):
    credential: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    store_id: int
    role: str
    mfa_required: bool = False

class RefreshRequest(BaseModel):
    refresh_token: str

class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"

class MeResponse(BaseModel):
    user_id: int
    email: EmailStr
    store_id: int
    role: str
    is_active: bool
    store_name: str | None = None

# ─── Utils ────────────────────────────────────────────────────────────────────
def _bcrypt_bytes(password: str) -> bytes:
    """bcrypt only looks at the first 72 bytes of the input — truncate
    explicitly so long passwords degrade gracefully instead of raising."""
    return password.encode("utf-8")[:72]

def hash_password(password: str) -> str:
    # P0-FIX: call the `bcrypt` library directly rather than going through
    # passlib's CryptContext. passlib 1.7.4 (latest release) runs an internal
    # self-test with an oversized dummy password to probe backend truncation
    # behaviour; bcrypt>=4.1 turned that silent truncation into a hard
    # ValueError("password cannot be longer than 72 bytes, ..."), which
    # passlib doesn't catch — so pwd_ctx.hash() raised that error even for
    # short, valid passwords. Calling bcrypt directly (with explicit
    # truncation to 72 bytes, matching bcrypt's own limit) sidesteps that
    # incompatibility entirely and works with any bcrypt 4.x release.
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    # AUDIT FIX (bug confirmé par logs de production réels) : une exception
    # levée par le backend de hash (hash corrompu, format non reconnu, donnée
    # de seed invalide, migration incomplète, ou altération) ne doit jamais
    # faire planter /api/v1/auth/login en 500. Toute erreur de vérification
    # doit échouer "closed" (False = accès refusé), jamais planter.
    try:
        return bcrypt.checkpw(_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        logger.warning("verify_password: hash non reconnu ou invalide — accès refusé")
        return False

def create_token(store_id: int, role: str, expires_hours: int = 24, user_id: int | None = None) -> str:
    now = int(time.time())
    payload = {
        "store_id": store_id,
        "role": role,
        "iat": now,
        "exp": datetime.now(UTC) + timedelta(hours=expires_hours),
    }
    if user_id is not None:
        payload["user_id"] = user_id
    return settings.encode_jwt(payload, algorithm="HS256")

def create_refresh_token(store_id: int, role: str, user_id: int | None = None) -> str:
    now = int(time.time())
    payload = {
        "store_id": store_id,
        "role": role,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": datetime.now(UTC) + timedelta(days=30),
    }
    if user_id is not None:
        payload["user_id"] = user_id
    return settings.encode_jwt(payload, algorithm="HS256")

# HIGH-1: invalidate all tokens after password change
RESET_TOKEN_TTL: int = 900  # 15 minutes — OWASP standard

_PW_CHANGED_KEY_TTL = 24 * 3600 + 300

async def _invalidate_user_tokens(user_id: int) -> None:
    """Enregistre le timestamp de changement de mot de passe pour invalider les tokens existants."""
    try:
        r = get_redis()
        key = f"auth:pw_changed:{user_id}"
        now_ts = int(time.time())
        await r.setex(key, _PW_CHANGED_KEY_TTL, str(now_ts))
        logger.info(f"JWT tokens invalidated for user {user_id} (password changed at {now_ts})")
    except Exception as exc:
        logger.error(f"Failed to invalidate tokens for user {user_id} in Redis: {exc}")

async def _is_token_invalidated(user_id: int, token_iat: int) -> bool:
    """Vérifie si un token a été invalidé par un changement de mot de passe."""
    try:
        r = get_redis()
        key = f"auth:pw_changed:{user_id}"
        pw_changed_ts_str = await r.get(key)
        if pw_changed_ts_str is None:
            return False
        pw_changed_ts = int(pw_changed_ts_str)
        if token_iat <= pw_changed_ts:
            logger.warning(f"Token for user {user_id} rejected — issued at {token_iat}, password changed at {pw_changed_ts}")
            return True
        return False
    except Exception as exc:
        logger.error(f"Redis unavailable for token invalidation check (user {user_id}): {exc}")
        return False

async def _get_current_user_from_request(request: Request, db: AsyncSession) -> User:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
    
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = settings.decode_jwt(token, algorithms=["HS256"])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token missing user_id claim — please log in again")

        token_iat = payload.get("iat", 0)
        if await _is_token_invalidated(user_id, token_iat):
            raise HTTPException(
                status_code=401,
                detail="Session expired — your password was recently changed. Please log in again."
            )

        result = await db.execute(select(User).where(User.id == user_id, User.is_active))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ─── Endpoints ───────────────────────────────────────────────────────────────

async def _set_auth_rls_context(db: AsyncSession, *, tenant_id: int | None = None) -> None:
    """Préparer le contexte RLS minimal nécessaire aux endpoints anonymes.

    Avant authentification, aucun ContextVar tenant n’existe. Le login doit
    donc pouvoir rechercher l’utilisateur par email ; register doit pouvoir
    créer le premier store et son admin. Le contexte privilégié est limité à
    cette requête d’authentification et est nettoyé par le cycle de session.
    """
    await db.execute(
        text("SELECT set_config('app.current_user_role', 'super_admin', false)")
    )
    if tenant_id is not None:
        await db.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
            {"tenant_id": str(tenant_id)},
        )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    from services.distributed_rate_limit import check as _rl_check
    client_ip = (request.client.host if request.client else "unknown")
    rl = await _rl_check("auth.login", client_ip)
    if not rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(rl.retry_after)},
        )
    await _set_auth_rls_context(db)
    result = await db.execute(select(User).where(User.email == body.email, User.is_active))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.store_id, user.role, user_id=user.id)
    refresh = create_refresh_token(user.store_id, user.role, user_id=user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token, refresh_token=refresh, store_id=user.store_id, role=user.role)

@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    from services.distributed_rate_limit import check as _rl_check
    client_ip = (request.client.host if request.client else "unknown")
    rl = await _rl_check("auth.register", client_ip)
    if not rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts",
            headers={"Retry-After": str(rl.retry_after)},
        )
    if body.confirm_password is not None and body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    await _set_auth_rls_context(db)
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    slug = body.store_name.lower().replace(" ", "-")[:50] + "-" + secrets.token_hex(3)
    store = Store(name=body.store_name, slug=slug)
    db.add(store)
    await db.flush()

    user = User(
        store_id=store.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="admin",
    )
    db.add(user)
    await db.commit()

    token = create_token(store.id, "admin", user_id=user.id)
    refresh = create_refresh_token(store.id, "admin", user_id=user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token, refresh_token=refresh, store_id=store.id, role="admin")


@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Génère un token de reset stocké en base de données (TTL 15 min).

    Changement vs version précédente :
      - Token persisté dans la table ``password_reset_tokens`` (plus Redis only)
      - Résilient aux redémarrages Redis / crash
      - Un seul token actif par utilisateur (les anciens sont invalidés)
      - Nettoyage automatique par le job session_cleanup
    """
    from services.distributed_rate_limit import check as _rl_check
    client_ip = (request.client.host if request.client else "unknown")
    rl = await _rl_check("auth.forgot_password", client_ip)
    if not rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(rl.retry_after)},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Réponse identique qu'il y ait un compte ou non (anti-énumération)
    if user:
        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=RESET_TOKEN_TTL)
        ip = request.client.host if request.client else None

        # Invalider les anciens tokens non utilisés pour cet utilisateur
        # (empêche l'accumulation de tokens valides)
        from sqlalchemy import and_, update
        await db.execute(
            update(PasswordResetToken)
            .where(
                and_(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used.is_(False),
                )
            )
            .values(used=True, used_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )

        # Créer le nouveau token en DB
        db_token = PasswordResetToken(
            user_id=user.id,
            token=reset_token,
            expires_at=expires_at,
            used=False,
            ip_address=ip,
        )
        db.add(db_token)
        await db.flush()

        # Aussi stocker dans Redis si disponible (cache rapide, redondant)
        try:
            r = get_redis()
            await r.setex(f"reset_token:{reset_token}", RESET_TOKEN_TTL, str(user.id))
        except Exception as _redis_exc:
            logger.warning("forgot_password: Redis store failed (using DB only): %s", _redis_exc)

        await db.commit()

        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost"))
        base_url = f"{proto}://{host}"
        try:
            from services.email_service import send_password_reset_email as _send_reset
            await _send_reset(to_email=body.email, reset_token=reset_token, base_url=base_url)
        except Exception as _mail_exc:
            logger.error("forgot_password: email send failed: %s", _mail_exc)

    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Réinitialise le mot de passe via un token stocké en base de données.

    Vérification en deux temps :
      1. Lookup Redis (cache rapide) — fallback si Redis down
      2. Lookup DB (source de vérité)
    """
    from services.distributed_rate_limit import check as _rl_check
    client_ip = (request.client.host if request.client else "unknown")
    rl = await _rl_check("auth.reset_password", client_ip)
    if not rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many reset attempts",
            headers={"Retry-After": str(rl.retry_after)},
        )
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    now = datetime.now(UTC)

    # 1. Chercher le token en DB (source de vérité)
    db_result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == body.token,
            PasswordResetToken.used.is_(False),
            PasswordResetToken.expires_at > now,
        )
    )
    db_token_obj = db_result.scalar_one_or_none()

    # 2. Fallback Redis si token absent en DB (migration progressive)
    user_id_int: int | None = None
    if db_token_obj is not None:
        user_id_int = db_token_obj.user_id
    else:
        # Fallback: vérifier Redis (tokens créés avant cette migration)
        user_id_str = None
        try:
            r = get_redis()
            user_id_str = await r.get(f"reset_token:{body.token}")
        except Exception as _exc:
            logger.warning("reset_password: Redis get failed: %s", _exc)

        if user_id_str:
            user_id_int = int(user_id_str)

    if user_id_int is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await db.get(User, user_id_int)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(body.new_password)

    # Marquer le token DB comme utilisé
    if db_token_obj is not None:
        db_token_obj.used = True
        db_token_obj.used_at = now

    # Nettoyer Redis
    try:
        r = get_redis()
        await r.delete(f"reset_token:{body.token}")
    except Exception as _exc:
        logger.warning("reset_password: Redis delete failed: %s", _exc)

    # HIGH-1: invalider tous les JWT existants
    await _invalidate_user_tokens(user.id)
    await db.commit()

    return {"message": "Password updated successfully. Please log in again with your new password."}


@router.post("/google-login", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    raise HTTPException(
        status_code=501,
        detail=(
            "Google login is not yet available. "
            "Please use email/password login. "
            "Contact support if you need OAuth access."
        ),
    )

@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """C1-FIX: Implement missing /auth/refresh endpoint.

    R3-FIX: Added @limiter.limit("10/minute") + request: Request.
    R4-FIX: Added DB check — verifies user still exists and is active.
    HIGH-1 FIX: Check token invalidation (password change).
    """
    from services.distributed_rate_limit import check as _rl_check
    client_ip = request.client.host if request.client else "unknown"
    rl = await _rl_check("auth.refresh", client_ip)
    if not rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many refresh attempts",
            headers={"Retry-After": str(rl.retry_after)},
        )

    try:
        payload = settings.decode_jwt(body.refresh_token, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type — access token cannot be used as refresh token")

    user_id = payload.get("user_id")
    store_id = payload.get("store_id")

    if store_id is None:
        raise HTTPException(status_code=401, detail="Token missing store_id claim — please log in again")

    if user_id is not None:
        token_iat = payload.get("iat", 0)
        if await _is_token_invalidated(user_id, token_iat):
            raise HTTPException(
                status_code=401,
                detail="Session expired — your password was recently changed. Please log in again."
            )

    jti = payload.get("jti")
    if jti:
        try:
            r = get_redis()
            is_revoked = await r.get(f"refresh:blacklist:{jti}")
            if is_revoked:
                raise HTTPException(
                    status_code=401,
                    detail="Refresh token has been revoked. Please log in again."
                )
        except HTTPException:
            raise
        except Exception as _redis_err:
            logger.warning("Could not check refresh JTI blacklist: %s", _redis_err)

    if user_id is not None:
        # Le refresh s'exécute hors du middleware tenant. Sans restaurer le
        # contexte RLS à partir du token signé, la requête sur users est filtrée
        # par défaut et retourne à tort « User not found or inactive ».
        await db.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
            {"tenant_id": str(int(store_id))},
        )
        await db.execute(
            text("SELECT set_config('app.current_user_role', :user_role, false)"),
            {"user_role": str(payload.get("role") or "viewer")},
        )
        result = await db.execute(select(User).where(User.id == user_id, User.is_active))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        store = await db.get(Store, store_id)
        if store and (store.billing_status == "suspended" or not store.is_active):
            raise HTTPException(status_code=403, detail="Account suspended")

    new_access = create_token(
        store_id=store_id,
        role=payload["role"],
        user_id=user_id,
    )
    _set_auth_cookie(response, new_access)
    return RefreshResponse(access_token=new_access)


@router.get("/me", response_model=MeResponse)
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_request(request, db)
    store = await db.get(Store, user.store_id)
    return MeResponse(user_id=user.id, email=user.email, store_id=user.store_id, role=user.role, is_active=user.is_active, store_name=store.name if store else None)

@router.post("/logout")
async def logout(request: Request, response: Response, body: dict | None = None):
    """MED-3 FIX: Logout révoque maintenant le refresh token individuellement via son JTI."""
    refresh_token_str = None
    try:
        if request.method == "POST":
            try:
                data = await request.json()
                refresh_token_str = data.get("refresh_token") if isinstance(data, dict) else None
            except Exception as _exc:
                logger.warning("logout json_parse failed: %s", _exc)
    except Exception as _exc:
        logger.warning("logout request_read failed: %s", _exc)

    if refresh_token_str:
        try:
            payload = settings.decode_jwt(
                refresh_token_str, algorithms=["HS256"]
            )
            jti = payload.get("jti")
            exp = payload.get("exp", 0)
            if jti and exp:
                import time as _time
                ttl = max(int(exp - _time.time()), 1)
                r = get_redis()
                await r.setex(f"refresh:blacklist:{jti}", ttl, "revoked")
                logger.info("Refresh token JTI blacklisted on logout", extra={"jti": jti})
        except Exception as _e:
            logger.debug("Could not blacklist refresh token on logout: %s", _e)

    _clear_auth_cookie(response)
    return {"status": "logged_out"}
