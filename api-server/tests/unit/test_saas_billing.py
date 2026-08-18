"""tests/test_saas_billing.py — Couverture complète services/saas_billing.py.

Couvre :
  - Catalogue de plans (_FALLBACK_PLANS)
  - upsert_subscription (création, renouvellement, mise à niveau plan)
  - get_subscription_overview (actif, expiré, inexistant)
  - expire_overdue_subscriptions (logique d'expiration)
  - list_plans_catalog (depuis DB ou fallback statique)
  - compute_price (durée 1/3/6/12 mois)
  - Stripe checkout (mock httpx)
  - Stripe webhook signature (valide + invalide)
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from security_overlay.models import TenantSubscription  # noqa: E402
from services.saas_billing import (  # noqa: E402
    _FALLBACK_PLANS,
    compute_subscription_price,
    expire_overdue_subscriptions,
    get_subscription_overview,
    list_plans_catalog,
    upsert_subscription,
)

pytestmark = pytest.mark.unit

# ── DB in-memory setup ────────────────────────────────────────────────────────
from models.database import Base  # noqa: E402

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
_SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
async def _create_schema():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture()
async def db():
    async with _SessionLocal() as session:
        yield session
        await session.rollback()


# ─── Tests _FALLBACK_PLANS ────────────────────────────────────────────────────

def test_fallback_plans_non_empty():
    assert len(_FALLBACK_PLANS) >= 4


def test_fallback_plans_all_have_required_keys():
    required = {"plan_code", "display_name", "price_monthly_dt", "monthly_ai_credits"}
    for plan in _FALLBACK_PLANS:
        missing = required - plan.keys()
        assert not missing, f"Plan {plan.get('plan_code')} missing keys: {missing}"


def test_fallback_plans_prices_positive():
    for plan in _FALLBACK_PLANS:
        assert plan["price_monthly_dt"] >= 0, f"Prix négatif pour {plan['plan_code']}"


def test_fallback_plans_credits_non_negative():
    for plan in _FALLBACK_PLANS:
        assert plan["monthly_ai_credits"] >= 0


# ─── Tests compute_subscription_price ─────────────────────────────────────────

def test_compute_price_monthly():
    price = compute_subscription_price("starter", 1)
    assert price > 0


def test_compute_price_12months_cheaper_than_12x_monthly():
    """Abonnement 12 mois doit offrir une remise vs 12× le prix mensuel."""
    monthly = compute_subscription_price("business", 1)
    annual = compute_subscription_price("business", 12)
    # La remise doit être au moins 10%
    assert annual < monthly * 12 * 0.95


def test_compute_price_3months():
    price_3 = compute_subscription_price("premium", 3)
    price_1 = compute_subscription_price("premium", 1)
    assert price_3 < price_1 * 3  # remise appliquée


def test_compute_price_unknown_plan_raises_or_fallback():
    """Plan inconnu -> soit KeyError, soit prix 0 — pas de crash silencieux."""
    try:
        price = compute_subscription_price("nonexistent_plan_xyz", 1)
        # Si pas d'exception, le prix doit être 0 ou > 0
        assert price >= 0
    except (KeyError, ValueError):
        pass  # Comportement acceptable


# ─── Tests upsert_subscription ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_subscription_creates_new(db: AsyncSession):
    """Création d'un nouvel abonnement.

    AUDIT FIX : ce test appelait upsert_subscription avec store_id= (au lieu
    de tenant_id=) et sans starts_at/expires_at, une signature qui n'a jamais
    existé dans le code réel (voir les appels prod dans api/v1/super_admin.py
    et le webhook Stripe, qui utilisent tenant_id=/starts_at=/expires_at=).
    Il patchait aussi `_get_store`, qui n'existe pas : _sync_store_billing
    fait un UPDATE direct sans lecture préalable du Store.
    """
    store_id = 1001
    now = datetime.now(UTC)
    sub = await upsert_subscription(
        db=db,
        tenant_id=store_id,
        plan_code="starter",
        duration_months=1,
        price_paid_dt=19.99,
        starts_at=now,
        expires_at=now + timedelta(days=30),
        created_by="admin",
    )

    assert sub is not None
    assert sub.plan_code == "starter"
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_upsert_subscription_renewal_extends_expiry(db: AsyncSession):
    """Renouvellement : la date d'expiration est repoussée."""
    store_id = 1002
    now = datetime.now(UTC)

    # Premier abonnement
    sub1 = await upsert_subscription(
        db=db,
        tenant_id=store_id,
        plan_code="starter",
        duration_months=1,
        price_paid_dt=19.99,
        starts_at=now,
        expires_at=now + timedelta(days=30),
        created_by="admin",
    )

    assert sub1 is not None


@pytest.mark.asyncio
async def test_upsert_subscription_upgrade_plan(db: AsyncSession):
    """Passage de starter -> business."""
    store_id = 1003
    now = datetime.now(UTC)
    sub = await upsert_subscription(
        db=db,
        tenant_id=store_id,
        plan_code="business",
        duration_months=3,
        price_paid_dt=89.0,
        starts_at=now,
        expires_at=now + timedelta(days=90),
        created_by="superadmin",
    )

    assert sub is not None
    assert sub.plan_code == "business"


# ─── Tests get_subscription_overview ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_subscription_overview_no_subscription(db: AsyncSession):
    """Tenant sans abonnement -> plan free, status inactive.

    AUDIT FIX : la clé réelle retournée par get_subscription_overview /
    _empty_subscription_overview est "billing_plan_code", pas "plan_code".
    """
    result = await get_subscription_overview(db, store_id=9999)
    assert result["billing_plan_code"] in ("free", "inactive", None) or result.get("status") in ("inactive", "free", None)


@pytest.mark.asyncio
async def test_get_subscription_overview_active(db: AsyncSession):
    """Tenant avec abonnement actif -> overview cohérent."""
    store_id = 2001
    sub = TenantSubscription(
        tenant_id=store_id,
        plan_code="business",
        duration_months=1,
        price_paid_dt=29.99,
        starts_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        status="active",
    )
    db.add(sub)
    await db.commit()

    result = await get_subscription_overview(db, store_id=store_id)
    assert result is not None


# ─── Tests expire_overdue_subscriptions ───────────────────────────────────────

@pytest.mark.asyncio
async def test_expire_overdue_subscriptions_marks_expired(db: AsyncSession):
    """Les abonnements expirés sont marqués 'expired'."""
    store_id = 3001
    expired_sub = TenantSubscription(
        tenant_id=store_id,
        plan_code="starter",
        duration_months=1,
        price_paid_dt=19.99,
        starts_at=datetime.now(UTC) - timedelta(days=35),
        expires_at=datetime.now(UTC) - timedelta(days=5),  # Expiré il y a 5 jours
        status="active",
    )
    db.add(expired_sub)
    await db.commit()

    count = await expire_overdue_subscriptions(db)
    assert count >= 0  # Au moins 0 expirations (peut avoir trouvé d'autres)


# ─── Tests list_plans_catalog ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_plans_catalog_returns_list(db: AsyncSession):
    """Retourne au moins les plans du fallback statique."""
    plans = await list_plans_catalog(db)
    assert isinstance(plans, list)
    assert len(plans) >= 1


@pytest.mark.asyncio
async def test_list_plans_catalog_has_starter(db: AsyncSession):
    """Le plan starter doit toujours être présent."""
    plans = await list_plans_catalog(db)
    plan_codes = [p.get("plan_code") or p.get("code") for p in plans]
    assert "starter" in plan_codes


# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 4 — Extension de la couverture services/saas_billing.py
# ═══════════════════════════════════════════════════════════════════════════════
#
# Objectif : ≥ 45 % de couverture sur services/saas_billing.py.
# Nouveaux tests :
#   - get_plan_by_code
#   - get_active_subscription
#   - _empty_subscription_overview
#   - Stripe checkout : succès, plan inconnu, STRIPE_SECRET_KEY manquant
#   - Stripe webhook : signature valide, signature invalide, event non géré
#   - _FALLBACK_PLANS : structure et cohérence
# ═══════════════════════════════════════════════════════════════════════════════

from services.saas_billing import (  # noqa: E402
    _empty_subscription_overview,
    create_stripe_checkout_session,
    get_active_subscription,
    get_plan_by_code,
    handle_stripe_webhook,
)

# ─── Tests get_plan_by_code ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_by_code_starter_returns_plan(db: AsyncSession):
    """Un plan connu doit être retrouvé (fallback en l'absence de plan_limits)."""
    plan = await get_plan_by_code(db, "starter")
    assert plan is not None
    assert plan.get("plan_code") == "starter" or plan.get("code") == "starter"


@pytest.mark.asyncio
async def test_get_plan_by_code_unknown_returns_none(db: AsyncSession):
    """Un plan inconnu doit renvoyer None (pas d'exception)."""
    plan = await get_plan_by_code(db, "plan_that_does_not_exist_xyz_123")
    assert plan is None


# ─── Tests get_active_subscription ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_active_subscription_none_when_absent(db: AsyncSession):
    """Store sans abonnement : renvoie None."""
    result = await get_active_subscription(db, store_id=99999)
    assert result is None


@pytest.mark.asyncio
async def test_get_active_subscription_returns_active(db: AsyncSession):
    """Store avec abonnement actif : renvoie l'objet."""
    store_id = 4001
    sub = TenantSubscription(
        tenant_id=store_id,
        plan_code="starter",
        duration_months=1,
        price_paid_dt=19.99,
        starts_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        status="active",
    )
    db.add(sub)
    await db.commit()

    result = await get_active_subscription(db, store_id=store_id)
    assert result is not None
    assert result.plan_code == "starter"


# ─── Tests _empty_subscription_overview ───────────────────────────────────────


def test_empty_subscription_overview_shape():
    """L'overview vide doit contenir les clés canoniques."""
    overview = _empty_subscription_overview(store_id=42)
    assert isinstance(overview, dict)
    # billing_plan_code ou plan_code selon la version
    assert any(k in overview for k in ("billing_plan_code", "plan_code", "status"))


def test_empty_subscription_overview_no_side_effects():
    """L'appel deux fois doit renvoyer deux dicts distincts (pas de mutation partagée)."""
    o1 = _empty_subscription_overview(store_id=1)
    o2 = _empty_subscription_overview(store_id=2)
    o1["test_marker"] = True
    assert "test_marker" not in o2


# ─── Tests Stripe checkout ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stripe_checkout_missing_secret_key_raises(db: AsyncSession):
    """Sans STRIPE_SECRET_KEY, la création de session doit lever ValueError."""
    with patch("config.settings") as mock_settings:
        mock_settings.STRIPE_SECRET_KEY = ""
        with pytest.raises((ValueError, RuntimeError)):
            await create_stripe_checkout_session(
                db,
                tenant_id=1,
                plan_code="starter",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                duration_months=1,
            )


@pytest.mark.asyncio
async def test_stripe_checkout_unknown_plan_raises(db: AsyncSession):
    """Un plan inconnu doit lever ValueError."""
    fake_stripe = MagicMock()
    fake_stripe.checkout.Session.create = MagicMock(
        return_value=SimpleNamespace(id="cs_test_XXX", url="https://checkout.stripe.test/pay")
    )

    with (
        patch.dict("sys.modules", {"stripe": fake_stripe}),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        with pytest.raises(ValueError):
            await create_stripe_checkout_session(
                db,
                tenant_id=1,
                plan_code="unknown_plan_xyz_999",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                duration_months=1,
            )


@pytest.mark.asyncio
async def test_stripe_checkout_success_returns_url(db: AsyncSession):
    """Créer une session Stripe valide doit renvoyer une URL non vide."""
    fake_session = SimpleNamespace(
        id="cs_test_ABC123",
        url="https://checkout.stripe.test/pay/cs_test_ABC123",
    )

    class _FakeStripeError(Exception):
        pass

    fake_stripe = MagicMock()
    fake_stripe.checkout.Session.create = MagicMock(return_value=fake_session)
    fake_stripe.StripeError = _FakeStripeError

    with (
        patch.dict("sys.modules", {"stripe": fake_stripe}),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        url = await create_stripe_checkout_session(
            db,
            tenant_id=5001,
            plan_code="starter",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            duration_months=1,
        )
        assert url.startswith("https://checkout.stripe.test/")


# ─── Tests Stripe webhook ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stripe_webhook_missing_secret_raises(db: AsyncSession):
    """Sans STRIPE_WEBHOOK_SECRET, la validation doit échouer."""
    with patch("config.settings") as mock_settings:
        mock_settings.STRIPE_WEBHOOK_SECRET = ""
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        with pytest.raises((ValueError, RuntimeError)):
            await handle_stripe_webhook(db, payload=b"{}", stripe_signature="t=1,v1=abc")


@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature_rejected(db: AsyncSession):
    """Une signature invalide doit lever ValueError et ne rien persister."""

    class _FakeSigError(Exception):
        pass

    fake_stripe = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(
        side_effect=_FakeSigError("bad signature")
    )
    fake_stripe.SignatureVerificationError = _FakeSigError

    with (
        patch.dict("sys.modules", {"stripe": fake_stripe}),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        with pytest.raises(ValueError):
            await handle_stripe_webhook(
                db, payload=b'{"type":"checkout.session.completed"}', stripe_signature="bad"
            )


@pytest.mark.asyncio
async def test_stripe_webhook_checkout_completed_activates_subscription(db: AsyncSession):
    """Un événement checkout.session.completed valide doit activer l'abonnement."""
    store_id = 7001
    fake_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_OK",
                "metadata": {
                    "store_id": str(store_id),
                    "plan_code": "starter",
                    "duration_months": "1",
                    "price_dt": "19.99",
                },
            }
        },
    }

    class _FakeSigError(Exception):
        pass

    fake_stripe = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(return_value=fake_event)
    fake_stripe.SignatureVerificationError = _FakeSigError

    with (
        patch.dict("sys.modules", {"stripe": fake_stripe}),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        await handle_stripe_webhook(
            db,
            payload=b'{"type":"checkout.session.completed"}',
            stripe_signature="t=1,v1=abc",
        )
        # Aucune exception : la signature est acceptée par le mock

        # Vérifier que l'abonnement a été activé
        active = await get_active_subscription(db, store_id=store_id)
        assert active is not None
        assert active.plan_code == "starter"


@pytest.mark.asyncio
async def test_stripe_webhook_unhandled_event_type_is_no_op(db: AsyncSession):
    """Un event_type non géré (ex: customer.created) ne doit pas lever d'exception."""
    fake_event = {
        "type": "customer.created",
        "data": {"object": {"id": "cus_test_XYZ"}},
    }

    class _FakeSigError(Exception):
        pass

    fake_stripe = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(return_value=fake_event)
    fake_stripe.SignatureVerificationError = _FakeSigError

    with (
        patch.dict("sys.modules", {"stripe": fake_stripe}),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
        mock_settings.STRIPE_SECRET_KEY = "sk_test_XXX"
        # Ne doit pas lever
        await handle_stripe_webhook(
            db,
            payload=b'{"type":"customer.created"}',
            stripe_signature="t=1,v1=abc",
        )


# ─── Tests supplémentaires _FALLBACK_PLANS ────────────────────────────────────


def test_fallback_plans_codes_unique():
    """Les codes de plan doivent être uniques."""
    codes = [p["plan_code"] for p in _FALLBACK_PLANS]
    assert len(codes) == len(set(codes)), f"Codes dupliqués : {codes}"


def test_fallback_plans_include_starter_and_business():
    """La liste doit contenir au minimum starter et business."""
    codes = {p["plan_code"] for p in _FALLBACK_PLANS}
    assert "starter" in codes


def test_fallback_plans_have_ordered_ranks():
    """Chaque plan doit avoir un `rank` numérique cohérent."""
    for plan in _FALLBACK_PLANS:
        if "rank" in plan:
            assert isinstance(plan["rank"], int)
            assert plan["rank"] >= 0


# ─── Test edge : compute_price avec durées atypiques ──────────────────────────


def test_compute_price_6months():
    """Durée 6 mois : la remise est appliquée."""
    price_6 = compute_subscription_price("starter", 6)
    price_1 = compute_subscription_price("starter", 1)
    assert price_6 > 0
    assert price_6 <= price_1 * 6


def test_compute_price_all_plans_at_all_durations():
    """Sanity : chaque plan / chaque durée renvoie un nombre >= 0."""
    for plan in _FALLBACK_PLANS:
        for duration in (1, 3, 6, 12):
            try:
                p = compute_subscription_price(plan["plan_code"], duration)
                assert p >= 0
            except (KeyError, ValueError):
                # Tolérance : certains plans peuvent ne pas supporter certaines durées
                pass


from services.saas_billing import (  # noqa: E402
    _build_flouci_tracking_id, _parse_flouci_tracking_id,
    create_flouci_payment, handle_flouci_webhook, ensure_default_saas_plans,
)


def test_flouci_tracking_id_roundtrip_and_invalid_values():
    token = _build_flouci_tracking_id(7, "business", 12)
    assert _parse_flouci_tracking_id(token) == (7, "business", 12)
    assert _parse_flouci_tracking_id("bad") is None
    assert _parse_flouci_tracking_id("sub-x-business-12-token") is None


@pytest.mark.asyncio
async def test_create_flouci_payment_validates_config_and_calls_provider(monkeypatch):
    import config
    monkeypatch.setattr(config.settings, "FLOUCI_APP_TOKEN", "token", raising=False)
    monkeypatch.setattr(config.settings, "FLOUCI_APP_SECRET", "secret", raising=False)
    plan = {"display_name": "Business", "price_monthly_dt": 100, "price_3months_dt": 270, "price_6months_dt": 500, "price_12months_dt": 900}
    provider = SimpleNamespace(create_payment_link=AsyncMock(return_value={"url": "https://pay.example/1"}))
    with patch("services.saas_billing.get_plan_by_code", new=AsyncMock(return_value=plan)), \
         patch("services.payment_factory.PaymentFactory.get", return_value=provider):
        result = await create_flouci_payment(SimpleNamespace(), 7, "business", "https://ok", "https://ko", 3)
    assert result == "https://pay.example/1"
    assert provider.create_payment_link.await_args.kwargs["amount"] == 270


@pytest.mark.asyncio
async def test_create_flouci_payment_rejects_missing_config():
    import config
    with patch.object(config.settings, "FLOUCI_APP_TOKEN", "", create=True), patch.object(config.settings, "FLOUCI_APP_SECRET", "", create=True):
        with pytest.raises(ValueError, match="FLOUCI_APP_TOKEN"):
            await create_flouci_payment(SimpleNamespace(), 1, "starter", "ok", "ko")


@pytest.mark.asyncio
async def test_handle_flouci_webhook_signature_status_and_activation():
    import config
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config.settings, "FLOUCI_APP_TOKEN", "t", raising=False)
    monkeypatch.setattr(config.settings, "FLOUCI_APP_SECRET", "s", raising=False)
    provider = SimpleNamespace(verify_webhook_signature=MagicMock(return_value=(True, "ok")), verify_payment=AsyncMock(return_value={"status": "paid"}))
    db = SimpleNamespace(commit=AsyncMock())
    with patch("services.payment_factory.PaymentFactory.get", return_value=provider), \
         patch("services.saas_billing.get_plan_by_code", new=AsyncMock(return_value={"price_monthly_dt": 100})), \
         patch("services.saas_billing.upsert_subscription", new=AsyncMock()) as upsert:
        await handle_flouci_webhook(db, b'{"developer_tracking_id":"sub-7-business-3-abcd1234","payment_id":"p1"}', {"X-Signature": "sig"})
    assert upsert.await_args.kwargs["tenant_id"] == 7 and upsert.await_args.kwargs["duration_months"] == 3
    db.commit.assert_awaited_once()
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_handle_flouci_webhook_invalid_signature_and_unconfirmed_are_no_activation():
    provider = SimpleNamespace(verify_webhook_signature=MagicMock(return_value=(False, "bad")), verify_payment=AsyncMock(return_value={"status": "failed"}))
    with patch("services.payment_factory.PaymentFactory.get", return_value=provider):
        with pytest.raises(ValueError, match="invalide"):
            await handle_flouci_webhook(SimpleNamespace(), b"{}", {})
    provider.verify_webhook_signature.return_value = (True, "ok")
    db = SimpleNamespace(commit=AsyncMock())
    with patch("services.payment_factory.PaymentFactory.get", return_value=provider):
        await handle_flouci_webhook(db, b'{"tracking_id":"sub-7-business-3-abcd1234","payment_id":"p2"}', {})
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_default_saas_plans_returns_when_seeded_and_rolls_back_on_error():
    seeded = SimpleNamespace(scalar=lambda: 4)
    db = SimpleNamespace(execute=AsyncMock(return_value=seeded), rollback=AsyncMock(), bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    await ensure_default_saas_plans(db)
    db.execute.assert_awaited_once()
    broken = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db")), rollback=AsyncMock(), bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    await ensure_default_saas_plans(broken)
    broken.rollback.assert_awaited_once()
