import calendar
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# HIGH-4 FIX: Import limiter pour rate-limiting des endpoints super admin.
# Le tableau de bord super_admin n'avait aucune limite de débit — un attaquant
# ayant compromis un compte super_admin pouvait énumérer tous les tenants,
# sous-domaines, emails admins, et revenus sans friction.
from middleware.rate_limit import limiter
from models.database import Order, Store, User, get_db
from security_overlay.models import TenantSubscription
from security_overlay.plan_catalog import (
    DURATION_OPTIONS,
    PLAN_CATALOG,
    assert_plan_activation_allowed,
    get_price_for_duration,
)
from services.saas_billing import get_subscription_overview, upsert_subscription

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/super-admin",
    tags=["Super Admin"],
    # RBAC FIX: router-level dependency — every route in this file inherits
    # the super_admin check automatically. New routes cannot bypass it.
    # Individual Depends(check_super_admin) kept on each route for explicitness.
    dependencies=[],  # populated after check_super_admin is defined below
)
VALID_SUBSCRIPTION_STATUSES = {"active", "expired", "suspended", "cancelled", "all"}


class StoreDetail(BaseModel):
    id: int
    name: str
    admin_email: str | None
    plan_code: str
    status: str
    is_paid: bool
    created_at: datetime | None = None
    expires_at: datetime | None = None
    features: list[str] = []


class PaginatedStores(BaseModel):
    """MED-4 FIX: Réponse paginée pour list_all_stores.
    Remplace le SELECT * illimité qui chargeait tous les tenants en mémoire."""
    items: list[StoreDetail]
    total: int
    page: int
    page_size: int
    total_pages: int


class DashboardStats(BaseModel):
    total_stores: int
    active_subscriptions: int
    total_revenue_monthly: float
    total_orders: int
    expiring_soon: int
    expired_count: int
    created_at: datetime
    expires_at: datetime | None
    features: list[str] = []


class TenantSubscriptionDetail(BaseModel):
    id: int
    tenant_id: int
    store_name: str
    admin_email: str | None
    plan_code: str
    duration_months: int
    price_paid_dt: float
    starts_at: datetime
    expires_at: datetime
    status: str
    days_remaining: int
    reminder_7d_sent_at: datetime | None
    reminder_1d_sent_at: datetime | None
    blocked_at: datetime | None
    created_by: str | None
    created_at: datetime


class CreateSubscriptionRequest(BaseModel):
    plan_code: str = Field(..., description="starter | business | premium | pro_whatsapp")
    duration_months: int = Field(..., description="Durée : 3 | 6 | 12 mois")
    notes: str | None = None
    starts_at: datetime | None = None


class UpdateSubscriptionRequest(BaseModel):
    plan_code: str = Field(..., description="Nouveau plan")
    days: int = Field(30, ge=1, le=3650, description="Nouvelle durée en jours")


class PlanPricingResponse(BaseModel):
    plan_code: str
    plan_label: str
    pricing: list[dict]


async def check_super_admin(request: Request):
    try:
        from middleware.tenant import current_user_role as _cur_role
        role = _cur_role.get()
    except LookupError:
        role = getattr(request.state, "role", None)

    if role is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return True


# RBAC FIX: set router-level dependency now that check_super_admin is defined.
# Every route added to this router will automatically require super_admin.
router.dependencies = [Depends(check_super_admin)]


def _add_calendar_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _resolve_creator(request: Request) -> str:
    request_email = getattr(request.state, "user_email", None)
    if request_email:
        return f"admin:{request_email}"

    try:
        from middleware.tenant import current_user_email as _email
        email = _email.get()
        if email:
            return f"admin:{email}"
    except Exception as _exc:
        logger.warning("_resolve_creator failed: %s", _exc)
        pass

    return "admin:superadmin"


async def _get_active_tenant_sub(db: AsyncSession, tenant_id: int):
    # ORM FIX: remplace raw SQL SELECT * -> select() typé, portable SQLite/PG.
    stmt = (
        select(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == "active",
        )
        .order_by(TenantSubscription.expires_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        return None
    # Retourne un dict pour compatibilité avec les appelants qui font row["id"], etc.
    return {
        "id": obj.id, "tenant_id": obj.tenant_id, "plan_code": obj.plan_code,
        "duration_months": obj.duration_months, "price_paid_dt": obj.price_paid_dt,
        "starts_at": obj.starts_at, "expires_at": obj.expires_at, "status": obj.status,
        "blocked_at": obj.blocked_at, "reminder_7d_sent_at": obj.reminder_7d_sent_at,
        "reminder_1d_sent_at": obj.reminder_1d_sent_at, "notes": obj.notes,
        "created_by": obj.created_by, "created_at": obj.created_at,
    }


# HIGH-4 FIX: Rate limiting sur tous les endpoints super admin.
# Lectures : 30/min — permet le monitoring sans permettre l'énumération rapide.
# Écritures : 10/min — protège contre les modifications en masse automatisées.
# Sans ces limites, un token super_admin compromis = accès illimité à toutes les données.

@router.get("/stats", response_model=DashboardStats)
@limiter.limit("30/minute")
async def get_global_stats(request: Request, db: AsyncSession = Depends(get_db), _=Depends(check_super_admin)):
    total_stores = (await db.execute(select(func.count(Store.id)))).scalar() or 0
    total_orders = (await db.execute(select(func.count(Order.id)))).scalar() or 0

    now = datetime.now(UTC)
    in_7_days = now + timedelta(days=7)

    active_sub_rows = (
        await db.execute(
            select(
                TenantSubscription.price_paid_dt,
                TenantSubscription.duration_months,
                TenantSubscription.expires_at,
            ).where(TenantSubscription.status == "active")
        )
    ).all()
    active_subs = sum(
        1 for _price_paid_dt, _duration_months, expires_at in active_sub_rows
        if expires_at is None or expires_at >= now
    )
    revenue = sum(
        float(price_paid_dt or 0.0) / max(int(duration_months or 1), 1)
        for price_paid_dt, duration_months, expires_at in active_sub_rows
        if expires_at is None or expires_at >= now
    )

    # ORM FIX: COUNT avec filtre date — remplace 2 raw SQL text()
    expiring_soon = (
        await db.execute(
            select(func.count(TenantSubscription.id)).where(
                TenantSubscription.status == "active",
                TenantSubscription.expires_at >= now,
                TenantSubscription.expires_at <= in_7_days,
            )
        )
    ).scalar() or 0

    expired_count = (
        await db.execute(
            select(func.count(TenantSubscription.id)).where(
                TenantSubscription.status == "active",
                TenantSubscription.expires_at < now,
            )
        )
    ).scalar() or 0

    return DashboardStats(
        total_stores=total_stores,
        active_subscriptions=active_subs,
        total_revenue_monthly=float(revenue),
        total_orders=total_orders,
        expiring_soon=expiring_soon,
        expired_count=expired_count,
        created_at=now,
        expires_at=None,
        features=[],
    )


@router.get("/stores", response_model=PaginatedStores)
@limiter.limit("30/minute")
async def list_all_stores(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
    page: int = Query(1, ge=1, description="Numéro de page (1-based)"),
    page_size: int = Query(50, ge=1, le=200, description="Résultats par page (max 200)"),
    search: str | None = Query(None, max_length=100, description="Filtrer par nom ou email"),
) -> PaginatedStores:
    """MED-4 FIX: Pagination obligatoire sur /super-admin/stores.

    AVANT: SELECT * FROM stores sans LIMIT — avec 2000+ tenants cela charge
    potentiellement 2000 objets en mémoire + N+1 queries pour les subscriptions.
    CORRIGÉ: LIMIT/OFFSET + total count pour permettre la navigation côté client.

    Params:
      - page: page courante (1-based)
      - page_size: résultats par page (1–200, défaut 50)
      - search: filtre optionnel sur nom du store ou email admin (ILIKE)
    """
    offset = (page - 1) * page_size

    # Base query avec join admin email
    base_stmt = select(Store, User.email).outerjoin(
        User, (User.store_id == Store.id) & (User.role == "admin")
    )

    # Filtre de recherche optionnel
    if search:
        search_like = f"%{search}%"
        base_stmt = base_stmt.where(
            (Store.name.ilike(search_like)) | (User.email.ilike(search_like))
        )

    # Count total pour la pagination
    # FIX (v8) : wrap both queries in try/except + explicit rollback to avoid
    # InFailedSQLTransactionError if the COUNT or the LIMIT/OFFSET query fails
    # mid-transaction. Without this, a single failure poisons the AsyncSession
    # for all subsequent requests sharing that pool slot.
    try:
        count_stmt = select(func.count(Store.id))
        if search:
            search_like = f"%{search}%"
            count_stmt = count_stmt.outerjoin(
                User, (User.store_id == Store.id) & (User.role == "admin")
            ).where(
                (Store.name.ilike(search_like)) | (User.email.ilike(search_like))
            )
        total = (await db.execute(count_stmt)).scalar() or 0

        # Requête paginée
        paginated_stmt = base_stmt.order_by(Store.id.desc()).limit(page_size).offset(offset)
        result = await db.execute(paginated_stmt)
        rows = result.all()
    except Exception as exc:
        # Critical: roll back the failed transaction so the session is reusable.
        await db.rollback()
        logger.exception("list_all_stores: pagination query failed")
        raise HTTPException(500, "stores_list_failed") from exc

    stores = []
    for store, email in rows:
        sub_overview = await get_subscription_overview(db, store.id)
        plan_code = sub_overview.get("plan_code", "starter")
        plan_spec = PLAN_CATALOG.get(plan_code)
        stores.append(StoreDetail(
            id=store.id,
            name=store.name,
            admin_email=email,
            plan_code=plan_code,
            status=sub_overview.get("status", "none"),
            is_paid=sub_overview.get("is_paid", False),
            created_at=store.created_at,
            expires_at=sub_overview.get("expires_at"),
            features=sorted(list(plan_spec.features)) if plan_spec else [],
        ))

    return PaginatedStores(
        items=stores,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("/stores/{store_id}/suspend")
@limiter.limit("10/minute")
async def suspend_store(
    request: Request,
    store_id: int,
    reason: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    store = await db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")

    store.billing_status = "suspended"
    store.suspended_at = datetime.now(UTC)
    store.suspended_reason = reason

    # FIX: bulk UPDATE — was N separate UPDATEs (one per subscription row)
    # With 500 tenants and multiple subscriptions each, the loop was generating
    # N*subscriptions_per_tenant DB round-trips. Single UPDATE is O(1) round-trips.
    now_dt = datetime.now(UTC)
    await db.execute(
        update(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == store_id,
            TenantSubscription.status == "active",
        )
        .values(status="suspended", updated_at=now_dt)
        .execution_options(synchronize_session=False)
    )

    await db.commit()
    return {"status": "suspended", "store_id": store_id}


@router.post("/stores/{store_id}/reactivate")
@limiter.limit("10/minute")
async def reactivate_store(
    request: Request,
    store_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    store = await db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")

    store.billing_status = "active"
    store.suspended_at = None
    store.suspended_reason = None

    # FIX: bulk UPDATE — symmetric with suspend_store fix
    now_dt = datetime.now(UTC)
    await db.execute(
        update(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == store_id,
            TenantSubscription.status == "suspended",
        )
        .values(status="active", updated_at=now_dt)
        .execution_options(synchronize_session=False)
    )

    await db.commit()
    return {"status": "reactivated", "store_id": store_id}


@router.get("/tenants/{tenant_id}/subscriptions", response_model=list[TenantSubscriptionDetail])
@limiter.limit("30/minute")
async def get_tenant_subscriptions(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    # ORM FIX: SELECT JOIN — remplace raw SQL, retourne tuples typés
    stmt = (
        select(
            TenantSubscription,
            Store.name.label("store_name"),
            User.email.label("admin_email"),
        )
        .join(Store, Store.id == TenantSubscription.tenant_id)
        .outerjoin(
            User,
            and_(User.store_id == TenantSubscription.tenant_id, User.role == "admin"),
        )
        .where(TenantSubscription.tenant_id == tenant_id)
        .order_by(TenantSubscription.created_at.desc())
    )
    orm_rows = (await db.execute(stmt)).all()

    now = datetime.now(UTC)
    subs = []
    for ts, store_name, admin_email in orm_rows:
        expires = ts.expires_at
        if isinstance(expires, datetime):
            days_rem = max(0, (expires - now).days)
        else:
            days_rem = 0
        subs.append(TenantSubscriptionDetail(
            id=ts.id,
            tenant_id=ts.tenant_id,
            store_name=store_name or f"Store {ts.tenant_id}",
            admin_email=admin_email,
            plan_code=ts.plan_code or "starter",
            duration_months=ts.duration_months or 1,
            price_paid_dt=float(ts.price_paid_dt or 0),
            starts_at=ts.starts_at,
            expires_at=ts.expires_at,
            status=ts.status,
            days_remaining=days_rem,
            reminder_7d_sent_at=ts.reminder_7d_sent_at,
            reminder_1d_sent_at=ts.reminder_1d_sent_at,
            blocked_at=ts.blocked_at,
            created_by=ts.created_by,
            created_at=ts.created_at,
        ))
    return subs


# CTO audit fix: SuperAdmin.jsx posts to /super-admin/stores/{id}/subscriptions
# ("stores" prefix), keep the canonical /tenants/... but expose a "stores" alias.
@router.post("/stores/{tenant_id}/subscriptions")
@router.post("/tenants/{tenant_id}/subscriptions")
@limiter.limit("10/minute")
async def create_tenant_subscription(
    request: Request,
    tenant_id: int,
    body: CreateSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    if body.plan_code not in PLAN_CATALOG:
        raise HTTPException(400, f"Invalid plan_code. Valid: {list(PLAN_CATALOG.keys())}")
    duration_key = {1: "monthly", 3: "3months", 6: "6months", 12: "12months"}.get(body.duration_months)
    if duration_key is None:
        raise HTTPException(400, f"Invalid duration_months. Valid: 1, 3, 6, 12")
    try:
        assert_plan_activation_allowed(body.plan_code)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    store = await db.get(Store, tenant_id)
    if not store:
        raise HTTPException(404, "Store not found")

    starts_at = body.starts_at or datetime.now(UTC)
    expires_at = _add_calendar_months(starts_at, body.duration_months)
    price = get_price_for_duration(body.plan_code, duration_key)
    creator = _resolve_creator(request)

    sub = await upsert_subscription(
        db,
        tenant_id=tenant_id,
        plan_code=body.plan_code,
        duration_months=body.duration_months,
        price_paid_dt=price,
        starts_at=starts_at,
        expires_at=expires_at,
        created_by=creator,
        notes=body.notes,
    )
    await db.commit()
    return {"status": "created", "subscription_id": sub.id, "expires_at": expires_at.isoformat()}


# CTO audit fix: SuperAdmin.jsx puts to /super-admin/stores/{id}/subscription
# (singular). We expose both the canonical /tenants/.../current and the
# /stores/{id}/subscription alias — same handler, same rate limit.
@router.put("/stores/{tenant_id}/subscription")
@router.put("/tenants/{tenant_id}/subscriptions/current")
@limiter.limit("10/minute")
async def update_tenant_subscription(
    request: Request,
    tenant_id: int,
    body: UpdateSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    if body.plan_code not in PLAN_CATALOG:
        raise HTTPException(400, f"Invalid plan_code. Valid: {list(PLAN_CATALOG.keys())}")
    try:
        assert_plan_activation_allowed(body.plan_code)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    active_sub = await _get_active_tenant_sub(db, tenant_id)
    if not active_sub:
        raise HTTPException(404, "No active subscription found for this tenant")

    # ORM FIX: UPDATE expires_at += timedelta(days) en Python (portable SQLite/PG)
    # INTERVAL ':days days' n'est pas portable — timedelta est DB-agnostique.
    sub_obj = await db.get(TenantSubscription, active_sub["id"])
    if sub_obj is None:
        raise HTTPException(404, "Subscription record not found — concurrent modification?")
    sub_obj.plan_code = body.plan_code
    sub_obj.expires_at = sub_obj.expires_at + timedelta(days=body.days)
    sub_obj.updated_at = datetime.now(UTC)
    await db.commit()
    return {"status": "updated", "subscription_id": active_sub["id"]}


@router.get("/plans/pricing", response_model=list[PlanPricingResponse])
@limiter.limit("30/minute")
async def get_plans_pricing(request: Request, _=Depends(check_super_admin)):
    result = []
    for plan_code, plan in PLAN_CATALOG.items():
        pricing = []
        for months in DURATION_OPTIONS:
            price = get_price_for_duration(plan_code, months)
            pricing.append({"months": months, "price_dt": price})
        result.append(PlanPricingResponse(
            plan_code=plan_code,
            plan_label=getattr(plan, "label", plan_code),
            pricing=pricing,
        ))
    return result


# ─── GET /super-admin/subscriptions — vue globale tous tenants ─────────────────
@router.get("/subscriptions", response_model=list[TenantSubscriptionDetail])
@limiter.limit("30/minute")
async def list_all_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
    status: str | None = Query(
        None,
        description="Filtrer par statut: active | expired | suspended | cancelled | all",
    ),
    expiring_days: int | None = Query(
        None, ge=1, le=365,
        description="Ne retourner que les abonnements expirant dans N jours",
    ),
):
    """
    Vue globale de tous les abonnements tenant_subscriptions, tous tenants confondus.

    Endpoint manquant (404) — créé pour le tableau Super Admin / Abonnements.
    Réutilise la même structure que GET /tenants/{tenant_id}/subscriptions mais
    sans filtre tenant_id, avec filtres optionnels status/expiring_days.
    """
    if status is not None and status not in VALID_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            400,
            f"status invalide: {status!r}. Valeurs acceptées: {sorted(VALID_SUBSCRIPTION_STATUSES)}",
        )

    now = datetime.now(UTC)
    stmt = (
        select(
            TenantSubscription,
            Store.name.label("store_name"),
            User.email.label("admin_email"),
        )
        .join(Store, Store.id == TenantSubscription.tenant_id)
        .outerjoin(
            User,
            and_(
                User.store_id == TenantSubscription.tenant_id,
                User.role == "admin",
            ),
        )
    )

    if status and status != "all":
        stmt = stmt.where(TenantSubscription.status == status)

    if expiring_days is not None:
        horizon = now + timedelta(days=expiring_days)
        stmt = stmt.where(
            TenantSubscription.expires_at <= horizon,
            TenantSubscription.expires_at >= now,
        )

    stmt = stmt.order_by(TenantSubscription.expires_at.asc()).limit(500)
    rows = (await db.execute(stmt)).all()

    subs = []
    for subscription, store_name, admin_email in rows:
        expires = subscription.expires_at
        if isinstance(expires, datetime):
            days_rem = max(0, (expires - now).days)
        else:
            days_rem = 0
        subs.append(TenantSubscriptionDetail(
            id=subscription.id,
            tenant_id=subscription.tenant_id,
            store_name=store_name,
            admin_email=admin_email,
            plan_code=subscription.plan_code or "starter",
            duration_months=subscription.duration_months or 1,
            price_paid_dt=float(subscription.price_paid_dt or 0),
            starts_at=subscription.starts_at,
            expires_at=subscription.expires_at,
            status=subscription.status,
            days_remaining=days_rem,
            reminder_7d_sent_at=subscription.reminder_7d_sent_at,
            reminder_1d_sent_at=subscription.reminder_1d_sent_at,
            blocked_at=subscription.blocked_at,
            created_by=subscription.created_by,
            created_at=subscription.created_at,
        ))
    return subs


# ─── POST /super-admin/subscriptions/check-expired ──────────────────────────────
@router.post("/subscriptions/check-expired")
@limiter.limit("10/minute")
async def check_expired_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    """
    Bloque les boutiques dont l'abonnement actif a expiré.

    Endpoint manquant (404) — créé pour le bouton "Bloquer les expirés" du
    tableau Super Admin / Abonnements.

    Pour chaque tenant_subscriptions actif où expires_at < now() :
      - status -> 'expired'
      - blocked_at -> now()
      - Store.billing_status -> 'suspended' (réutilise le même mécanisme
        que suspend_store, donc TenantMiddleware bloque l'accès tenant)
    """
    # FIX: bulk operations — was N UPDATE rows + N db.get(Store) calls
    now = datetime.now(UTC)

    # 1. Find expired active subscriptions — only fetch tenant_ids, not full objects
    expired_stmt = select(TenantSubscription.tenant_id).where(
        TenantSubscription.status == "active",
        TenantSubscription.expires_at < now,
    )
    result = await db.execute(expired_stmt)
    tenant_ids = [row[0] for row in result.fetchall()]

    if not tenant_ids:
        return {"blocked": 0, "tenant_ids": []}

    # 2. Bulk UPDATE subscriptions → expired (single round-trip)
    await db.execute(
        update(TenantSubscription)
        .where(
            TenantSubscription.status == "active",
            TenantSubscription.expires_at < now,
        )
        .values(status="expired", blocked_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )

    # 3. Bulk UPDATE stores → suspended (single round-trip)
    await db.execute(
        update(Store)
        .where(
            Store.id.in_(tenant_ids),
            Store.billing_status != "suspended",
        )
        .values(
            billing_status="suspended",
            suspended_at=now,
            suspended_reason="subscription_expired",
        )
        .execution_options(synchronize_session=False)
    )

    # Invalider le cache Redis tenant_state pour chaque tenant impacté
    for tid in tenant_ids:
        try:
            from middleware.tenant import invalidate_tenant_state_cache
            invalidate_tenant_state_cache(tid)
        except Exception as _exc:
            logger.warning("check_expired_subscriptions: cache invalidation failed for tenant %s: %s", tid, _exc)

    await db.commit()

    logger_msg = f"check_expired_subscriptions: {len(tenant_ids)} tenant(s) bloqué(s): {tenant_ids}"
    import logging
    logger.info(logger_msg)

    return {"blocked": len(tenant_ids), "tenant_ids": tenant_ids}


# ─── POST /super-admin/subscriptions/send-reminders ─────────────────────────────
@router.post("/subscriptions/send-reminders")
@limiter.limit("10/minute")
async def send_subscription_reminders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_super_admin),
):
    """
    Envoie des rappels d'expiration d'abonnement à J-7 et J-1.

    Endpoint manquant (404) — créé pour le bouton "Envoyer rappels" du
    tableau Super Admin / Abonnements.

    Pour chaque abonnement actif :
      - expires_at entre [now, now+7j] et reminder_7d_sent_at IS NULL
        -> email J-7, marque reminder_7d_sent_at
      - expires_at entre [now, now+1j] et reminder_1d_sent_at IS NULL
        -> email J-1, marque reminder_1d_sent_at

    Best-effort : l'échec d'envoi email n'empêche pas le marquage des
    autres rappels (chaque envoi est isolé dans son propre try/except).
    """
    # BLOC 5-A+B FIX: Remplacé 2 raw SQL text() par ORM SQLAlchemy.
    # Bénéfices : paramétrage typé, pas de risque d'injection, portabilité SQLite/PG.
    now = datetime.now(UTC)
    horizon_7d = now + timedelta(days=7)
    horizon_1d = now + timedelta(days=1)

    try:
        from services.email_service import send_subscription_reminder_email
    except ImportError:
        send_subscription_reminder_email = None

    async def _send_and_mark(rows, field_name: str, days_label: str) -> int:
        sent = 0
        for row in rows:
            try:
                if send_subscription_reminder_email is not None and row.get("admin_email"):
                    await send_subscription_reminder_email(
                        to_email=row["admin_email"],
                        store_name=row["store_name"],
                        days_until_expiry=7 if days_label == "J-7" else 1,
                    )
                obj = await db.get(TenantSubscription, row["id"])
                if obj is None:
                    continue
                setattr(obj, field_name, now)
                db.add(obj)
                sent += 1
            except Exception as e:
                import logging
                logger.warning(
                    "send_subscription_reminders: échec envoi %s pour subscription %s: %s",
                    days_label, row["id"], e,
                )
        return sent

    # BLOC 5-A FIX: J-7 — ORM (remplace raw SQL)
    stmt_7d = (
        select(
            TenantSubscription.id,
            TenantSubscription.expires_at,
            TenantSubscription.plan_code,
            Store.name.label("store_name"),
            User.email.label("admin_email"),
        )
        .join(Store, Store.id == TenantSubscription.tenant_id)
        .outerjoin(
            User,
            and_(User.store_id == TenantSubscription.tenant_id, User.role == "admin"),
        )
        .where(
            TenantSubscription.status == "active",
            TenantSubscription.expires_at <= horizon_7d,
            TenantSubscription.expires_at > now,
            TenantSubscription.reminder_7d_sent_at.is_(None),
        )
    )
    result_7d = await db.execute(stmt_7d)
    rows_7d = result_7d.mappings().all()

    # BLOC 5-B FIX: J-1 — ORM (remplace raw SQL)
    stmt_1d = (
        select(
            TenantSubscription.id,
            TenantSubscription.expires_at,
            TenantSubscription.plan_code,
            Store.name.label("store_name"),
            User.email.label("admin_email"),
        )
        .join(Store, Store.id == TenantSubscription.tenant_id)
        .outerjoin(
            User,
            and_(User.store_id == TenantSubscription.tenant_id, User.role == "admin"),
        )
        .where(
            TenantSubscription.status == "active",
            TenantSubscription.expires_at <= horizon_1d,
            TenantSubscription.expires_at > now,
            TenantSubscription.reminder_1d_sent_at.is_(None),
        )
    )
    result_1d = await db.execute(stmt_1d)
    rows_1d = result_1d.mappings().all()

    reminders_7d_sent = await _send_and_mark(rows_7d, "reminder_7d_sent_at", "J-7")
    reminders_1d_sent = await _send_and_mark(rows_1d, "reminder_1d_sent_at", "J-1")

    await db.commit()

    return {
        "reminders_7d_sent": reminders_7d_sent,
        "reminders_1d_sent": reminders_1d_sent,
    }
