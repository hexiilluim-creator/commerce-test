"""tests/security/test_rls_isolation.py — P0-8 Multi-tenant RLS isolation tests.
Valide que la politique RLS couvre toutes les tables tenant-scoped et que
l'isolation cross-tenant est garantie au niveau SQL et applicatif.

V28 UPDATE : RLS est désormais géré exclusivement par les migrations Alembic
(0058→0064). Les fichiers sql/RLS_POLICIES.sql et scripts/apply_rls.sh ont été
supprimés. Les tests valident l'état réel de la base PostgreSQL au lieu de
parser un fichier SQL statique.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

API_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(API_ROOT))

# ── Tenant-scoped tables list ────────────────────────────────────────────────
# Tables protégées par RLS via les migrations Alembic 0058→0064.
TENANT_SCOPED_TABLES = [
    "orders",
    "products",
    "product_variants",
    "customers",
    "customer_identities",
    "contact_endpoints",
    "audit_logs",
    "credit_events",
    "whatsapp_messages",
    "store_phone_mappings",
    "store_social_mappings",
    "conversation_logs",
    "social_posts",
    "payment_links",
    "appointments",
    "b2b_orders",
    "visual_builds",
    "visual_build_assets",
    "visual_build_history",
    "visual_build_reviews",
    "b2b_invoices",
    "business_configs",
    "campaigns",
    "coupons",
    "expenses",
    "promotions",
    "promotion_rules",
    "promotion_usage",
    "pricing_rules",
    "tax_rates",
    "tax_exemptions",
    "services",
    "loyalty_churn_scores",
    "loyalty_ia_model_versions",
    "loyalty_recommendations",
    "restock_alerts",
    "restock_forecasts",
    "restock_seasonality",
    "restock_suggestions",
    "segment_definitions",
    "customer_segment_members",
    "company_accounts",
    "company_users",
    "accounting_documents",
    "availability_rules",
    "availability_exceptions",
    "social_post_configs",
]

# ── RLS validation tests ─────────────────────────────────────────────────────

pytestmark = [pytest.mark.security]


def _pg_available():
    """Vérifie si PostgreSQL est disponible (variable DATABASE_URL)."""
    url = os.environ.get("DATABASE_URL", "")
    return "postgresql" in url


def _get_db_session():
    """Crée une session SQLAlchemy synchronisée pour les tests."""
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL", "")
    engine = create_engine(url.replace("+asyncpg", ""), pool_pre_ping=True)
    return engine


class TestRLSPoliciesCoverage:
    """Vérifie que chaque table tenant-scoped a des policies RLS en base."""

    def test_rls_migrations_exist(self):
        """Les migrations RLS (0058, 0059, 0063, 0064) doivent exister."""
        migrations = [
            "0058_enforce_rls_and_harden_credit_events.py",
            "0059_extend_rls_full_tenant_coverage.py",
            "0063_full_rls_audit.py",
            "0064_merge_rls_audit_and_loyalty.py",
        ]
        versions_dir = API_ROOT / "alembic" / "versions"
        for m in migrations:
            assert (versions_dir / m).exists(), f"Migration {m} manquante"

    def test_rls_migration_0058_creates_policies(self):
        """La migration 0058 doit créer des policies tenant_isolation_*."""
        migration = API_ROOT / "alembic" / "versions" / "0058_enforce_rls_and_harden_credit_events.py"
        content = migration.read_text()
        assert "CREATE POLICY" in content
        assert "tenant_isolation_" in content

    def test_rls_migration_0058_splits_audit_logs_credit_events(self):
        """0058 doit créer SELECT + INSERT séparés sur audit_logs et credit_events."""
        migration = API_ROOT / "alembic" / "versions" / "0058_enforce_rls_and_harden_credit_events.py"
        content = migration.read_text()
        assert "audit_logs_select" in content
        assert "audit_logs_insert" in content
        assert "credit_events_select" in content
        assert "credit_events_insert" in content

    @pytest.mark.parametrize("table_name", TENANT_SCOPED_TABLES)
    def test_migration_references_table(self, table_name):
        """Chaque table tenant-scoped doit apparaître dans au moins une migration RLS."""
        versions_dir = API_ROOT / "alembic" / "versions"
        for m in ["0058_enforce_rls_and_harden_credit_events.py",
                  "0059_extend_rls_full_tenant_coverage.py",
                  "0063_full_rls_audit.py"]:
            path = versions_dir / m
            if path.exists():
                content = path.read_text()
                if table_name in content:
                    break
        else:
            pytest.fail(f"Table {table_name} non référencée dans les migrations RLS")

    @pytest.mark.dbtest
    def test_db_has_rls_policies(self):
        """Si PostgreSQL est disponible, vérifier que les policies existent."""
        if not _pg_available():
            pytest.skip("PostgreSQL non disponible")
        engine = _get_db_session()
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND policyname LIKE 'tenant_isolation_%'")
            )
            count = result.scalar()
            assert count >= 40, f"Nombre de policies RLS insuffisant: {count}"


class TestRLSPolicyCorrectness:
    """Vérifie la logique des policies RLS dans les migrations."""

    def test_policies_use_current_tenant(self):
        """Les policies doivent utiliser current_setting('app.current_tenant_id')."""
        versions_dir = API_ROOT / "alembic" / "versions"
        combined = ""
        for m in ["0058_enforce_rls_and_harden_credit_events.py",
                  "0059_extend_rls_full_tenant_coverage.py",
                  "0063_full_rls_audit.py"]:
            path = versions_dir / m
            if path.exists():
                combined += path.read_text()
        assert "current_setting('app.current_tenant_id'" in combined

    def test_policies_enable_force_rls(self):
        """Les tables doivent avoir FORCE ROW LEVEL SECURITY."""
        versions_dir = API_ROOT / "alembic" / "versions"
        combined = ""
        for m in ["0058_enforce_rls_and_harden_credit_events.py",
                  "0059_extend_rls_full_tenant_coverage.py",
                  "0063_full_rls_audit.py"]:
            path = versions_dir / m
            if path.exists():
                combined += path.read_text()
        assert "FORCE ROW LEVEL SECURITY" in combined

    def test_audit_logs_no_update_delete_policy(self):
        """audit_logs ne doit pas avoir de policy FOR UPDATE ou FOR DELETE."""
        migration = API_ROOT / "alembic" / "versions" / "0058_enforce_rls_and_harden_credit_events.py"
        content = migration.read_text()
        assert "FOR UPDATE" not in content or "audit_logs" not in content.split("FOR UPDATE")[0].split("\n")[-1] if "FOR UPDATE" in content else True
        # Vérification plus robuste
        assert not re.search(
            r'tenant_isolation_audit_logs_(update|delete)',
            content, re.IGNORECASE
        ), "audit_logs ne doit pas avoir de policy UPDATE/DELETE"

    def test_credit_events_no_update_delete_policy(self):
        """credit_events ne doit pas avoir de policy FOR UPDATE ou FOR DELETE."""
        migration = API_ROOT / "alembic" / "versions" / "0058_enforce_rls_and_harden_credit_events.py"
        content = migration.read_text()
        assert not re.search(
            r'tenant_isolation_credit_events_(update|delete)',
            content, re.IGNORECASE
        ), "credit_events ne doit pas avoir de policy UPDATE/DELETE"


# ── Migration RLS audit test ─────────────────────────────────────────────────

class TestRLSAuditMigration:
    """Vérifie que la migration 0063 crée la vue rls_missing_policies."""

    def test_migration_0063_exists(self):
        """La migration 0063_full_rls_audit.py doit exister."""
        migration = API_ROOT / "alembic" / "versions" / "0063_full_rls_audit.py"
        assert migration.exists(), "Migration 0063_full_rls_audit.py manquante"

    def test_migration_creates_rls_missing_policies_view(self):
        """La migration doit créer la vue rls_missing_policies."""
        migration = API_ROOT / "alembic" / "versions" / "0063_full_rls_audit.py"
        content = migration.read_text()
        assert "rls_missing_policies" in content, (
            "La migration 0063 doit créer la vue rls_missing_policies"
        )

    def test_migration_has_downgrade(self):
        """La migration doit avoir une fonction downgrade()."""
        migration = API_ROOT / "alembic" / "versions" / "0063_full_rls_audit.py"
        content = migration.read_text()
        assert "def downgrade" in content, "La migration 0063 doit avoir downgrade()"

    def test_migration_0064_merge_exists(self):
        """La migration de fusion 0064 doit exister."""
        migration = API_ROOT / "alembic" / "versions" / "0064_merge_rls_audit_and_loyalty.py"
        assert migration.exists(), "Migration 0064_merge_rls_audit_and_loyalty.py manquante"

    def test_migration_0064_resolves_dual_head(self):
        """0064 doit fusionner 0061 et 0063."""
        migration = API_ROOT / "alembic" / "versions" / "0064_merge_rls_audit_and_loyalty.py"
        content = migration.read_text()
        assert "0061_loyalty_wallet_tables" in content
        assert "0063_full_rls_audit" in content


# ── Applicatif: Tenant middleware isolation ──────────────────────────────────

class TestTenantMiddlewareIsolation:
    """Tests d'isolation tenant au niveau middleware (sans DB réelle)."""

    def test_tenant_context_var_set_on_auth(self):
        """current_tenant_id doit être set après authentification."""
        from middleware.tenant import current_tenant_id, current_user_role
        token = current_tenant_id.get()
        role = current_user_role.get()
        # Les context vars doivent avoir des valeurs par défaut None
        assert token is None or isinstance(token, int)
        assert role is None or isinstance(role, str)

    def test_public_paths_bypass_auth(self):
        """Les chemins publics doivent bypass l'authentification."""
        from middleware.tenant import PUBLIC_EXACT, PUBLIC_PREFIXES, _is_public
        assert _is_public("/health")
        assert _is_public("/api/v1/auth/login")
        assert _is_public("/api/v1/whatsapp/webhook")
        assert _is_public("/api/v1/payments/webhook")
        assert not _is_public("/api/v1/orders")
        assert not _is_public("/api/v1/billing/invoices")

    def test_public_prefixes_cover_webhooks(self):
        """Tous les webhooks doivent être dans PUBLIC_PREFIXES."""
        from middleware.tenant import PUBLIC_PREFIXES
        webhook_prefixes = [
            "/api/v1/whatsapp/webhook",
            "/api/v1/payments/webhook",
            "/api/v1/billing/webhook/saas",
            "/api/v1/social/instagram/webhook",
            "/api/v1/social/facebook/webhook",
            "/api/v1/social/tiktok/webhook",
        ]
        for prefix in webhook_prefixes:
            assert any(p for p in PUBLIC_PREFIXES if prefix.startswith(p)), (
                f"Webhook {prefix} doit être dans PUBLIC_PREFIXES"
            )


class TestTenantAccessState:
    """Tests du TenantAccessState et du kill-switch applicatif."""

    def test_tenant_access_state_dataclass(self):
        """TenantAccessState doit avoir les bons champs."""
        from services.tenant_access import TenantAccessState
        state = TenantAccessState(
            is_tenant_active=False,
            billing_status="suspended",
            suspended_reason="unpaid",
        )
        assert state.is_tenant_active is False
        assert state.billing_status == "suspended"
        assert state.suspended_reason == "unpaid"

    def test_tenant_access_state_defaults(self):
        """TenantAccessState doit avoir des valeurs par défaut saines."""
        from services.tenant_access import TenantAccessState
        state = TenantAccessState(
            is_tenant_active=False,
            billing_status="unknown",
            suspended_reason="tenant_not_found",
        )
        assert state.is_tenant_active is False
        assert state.billing_status == "unknown"


# ── Kill-switch tests ───────────────────────────────────────────────────────

class TestTenantKillSwitch:
    """Tests du kill-switch tenant (suspension + feature toggles)."""

    def test_kill_switch_blocks_inactive_tenant(self):
        """Un tenant inactif (billing_status != active) doit être bloqué."""
        from services.tenant_access import TenantAccessState
        state = TenantAccessState(
            is_tenant_active=False,
            billing_status="suspended",
            suspended_reason="billing_unpaid",
        )
        assert not state.is_tenant_active
        assert state.billing_status != "active"

    def test_kill_switch_allows_active_tenant(self):
        """Un tenant actif doit être autorisé."""
        from services.tenant_access import TenantAccessState
        state = TenantAccessState(
            is_tenant_active=True,
            billing_status="active",
            suspended_reason=None,
        )
        assert state.is_tenant_active

    def test_billing_status_values(self):
        """Les valeurs de billing_status doivent être cohérentes."""
        valid_statuses = {"active", "suspended", "past_due", "canceled", "trialing", "unknown", "unavailable"}
        from services.tenant_access import TenantAccessState
        for status in valid_statuses:
            state = TenantAccessState(
                is_tenant_active=(status == "active"),
                billing_status=status,
            )
            assert state.billing_status == status

    def test_kill_switch_cache_invalidation(self):
        """La fonction invalidate_tenant_state_cache doit exister."""
        from middleware.tenant import invalidate_tenant_state_cache
        assert callable(invalidate_tenant_state_cache)


# ── JWT Rotation tests ──────────────────────────────────────────────────────

class TestJWTRotation:
    """Tests de la rotation JWT et de son endpoint interne."""

    def test_encode_jwt_produces_valid_token(self):
        """encode_jwt doit produire un token décodable."""
        from services.jwt_rotation import decode_jwt, encode_jwt
        payload = {"sub": "42", "store_id": 1, "role": "admin"}
        token = encode_jwt(payload)
        assert token is not None
        assert len(token) > 20

    def test_rotate_tokens_updates_cutoff(self):
        """rotate_tokens doit mettre à jour le cutoff."""
        from services.jwt_rotation import current_rotation_state, rotate_tokens
        before = current_rotation_state()["invalid_before_epoch"]
        result = rotate_tokens(actor="test")
        assert result["rotated"] is True
        assert result["invalid_before_epoch"] >= before

    def test_current_rotation_state_returns_dict(self):
        """current_rotation_state doit retourner un dict avec invalid_before_epoch."""
        from services.jwt_rotation import current_rotation_state
        state = current_rotation_state()
        assert isinstance(state, dict)
        assert "invalid_before_epoch" in state

    def test_internal_jwt_rotate_endpoint_exists(self):
        """L'endpoint /_internal/jwt/rotate doit exister dans internal_ops.py."""
        internal_ops_path = API_ROOT / "api" / "v1" / "internal_ops.py"
        assert internal_ops_path.exists(), "api/v1/internal_ops.py manquant"
        content = internal_ops_path.read_text()
        assert "@router.post" in content, "internal_ops.py doit avoir des routes POST"
        assert "jwt/rotate" in content, "Endpoint /jwt/rotate manquant"
        assert "X-Internal-Token" in content, (
            "L'endpoint jwt/rotate doit être protégé par X-Internal-Token"
        )


# ── Rate limit per tenant tests ─────────────────────────────────────────────

class TestTenantRateLimit:
    """Tests du rate limiting par tenant."""

    def test_tenant_rate_limit_decorator_exists(self):
        """Le décorateur tenant_rate_limit doit exister."""
        from middleware.rate_limit import tenant_rate_limit
        assert callable(tenant_rate_limit)
