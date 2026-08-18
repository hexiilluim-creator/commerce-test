"""
tests/security/test_p0_p1_enterprise_controls.py
=================================================
Tests de contrôle de sécurité enterprise — P0 / P1.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import psycopg2
import pytest


def _get_database_url() -> str:
    return os.getenv(
        "TEST_DATABASE_URL",
        os.getenv("DATABASE_URL", "postgresql://autocommerce:autocommerce@localhost:5432/autocommerce_prod"),
    )

def _pg_conn():
    url = _get_database_url().replace("postgresql+asyncpg://", "postgresql://")
    scheme = urlparse(url).scheme.lower()
    if not scheme.startswith("postgresql"):
        pytest.skip(
            "tests/security/test_p0_p1_enterprise_controls.py requiert une base PostgreSQL via TEST_DATABASE_URL ou DATABASE_URL"
        )
    try:
        return psycopg2.connect(url)
    except (psycopg2.OperationalError, psycopg2.ProgrammingError) as exc:
        pytest.skip(f"Base PostgreSQL de sécurité indisponible pour les tests RLS: {exc}")

def _fetch(query: str, params=()) -> list[dict]:
    with _pg_conn() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

TENANT_TABLES_DIRECT = [
    "orders", "products", "product_variants", "customers", "customer_identities",
    "contact_endpoints", "audit_logs", "credit_events", "whatsapp_messages",
    "store_phone_mappings", "store_social_mappings", "conversation_logs",
    "business_configs", "services", "availability_rules", "availability_exceptions",
    "appointments", "social_post_configs", "social_posts", "payment_links",
    "tax_rates", "tax_exemptions", "campaigns", "promotions", "promotion_rules",
    "coupons", "promotion_usage", "accounting_documents", "expenses",
    "company_accounts", "company_users", "pricing_rules", "b2b_orders", "b2b_invoices",
    "segment_definitions", "customer_segment_members", "loyalty_recommendations",
    "loyalty_churn_scores", "loyalty_ia_model_versions", "restock_forecasts",
    "restock_alerts", "restock_suggestions", "restock_seasonality", "visual_builds",
    "visual_build_history"
]

TENANT_TABLES_JOIN = ["visual_build_assets", "visual_build_reviews"]
ALL_TENANT_TABLES = TENANT_TABLES_DIRECT + TENANT_TABLES_JOIN
IMMUTABLE_TABLES = {"audit_logs", "credit_events"}

@pytest.fixture(scope="session")
def rls_status() -> dict[str, dict]:
    rows = _fetch("SELECT c.relname AS tablename, c.relrowsecurity AS rowsecurity, c.relforcerowsecurity AS forcepolicies FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'")
    return {r["tablename"]: r for r in rows}

@pytest.fixture(scope="session")
def policy_status() -> dict[str, list[dict]]:
    rows = _fetch("SELECT c.relname AS tablename, p.polname, p.polcmd, p.polpermissive FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'")
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["tablename"], []).append(r)
    return result

@pytest.mark.parametrize("tablename", ALL_TENANT_TABLES)
def test_rls_enabled(tablename: str, rls_status: dict) -> None:
    assert tablename in rls_status
    assert rls_status[tablename]["rowsecurity"] is True

@pytest.mark.parametrize("tablename", ALL_TENANT_TABLES)
def test_force_rls_enabled(tablename: str, rls_status: dict) -> None:
    assert tablename in rls_status
    assert rls_status[tablename]["forcepolicies"] is True

@pytest.mark.parametrize("tablename", ALL_TENANT_TABLES)
def test_select_policy_exists(tablename: str, policy_status: dict) -> None:
    policies = policy_status.get(tablename, [])
    assert any(p["polcmd"] in ("r", "*") for p in policies)

@pytest.mark.parametrize("tablename", ALL_TENANT_TABLES)
def test_insert_policy_exists(tablename: str, policy_status: dict) -> None:
    policies = policy_status.get(tablename, [])
    assert any(p["polcmd"] in ("a", "*") for p in policies)

@pytest.mark.parametrize("tablename", [t for t in ALL_TENANT_TABLES if t not in IMMUTABLE_TABLES])
def test_update_policy_exists(tablename: str, policy_status: dict) -> None:
    policies = policy_status.get(tablename, [])
    assert any(p["polcmd"] in ("w", "*") for p in policies)

@pytest.mark.parametrize("tablename", [t for t in ALL_TENANT_TABLES if t not in IMMUTABLE_TABLES])
def test_delete_policy_exists(tablename: str, policy_status: dict) -> None:
    policies = policy_status.get(tablename, [])
    assert any(p["polcmd"] in ("d", "*") for p in policies)

def _set_tenant(cur, tenant_id: str) -> None:
    cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))

TENANT_A = "1"
TENANT_B = "2"

@pytest.mark.parametrize("tablename", ["products", "orders"])
def test_cross_tenant_isolation_basic(tablename: str) -> None:
    """
    Test basique d'isolation cross-tenant par injection SQL directe.
    On vérifie que même si on essaie de forcer un store_id différent, le RLS bloque ou filtre.
    """
    conn = _pg_conn()  # skips the test outright if no Postgres DB is configured
    try:
        with conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                _set_tenant(cur, TENANT_B)
                # Tenter de lire les données de A en étant B
                cur.execute(f"SELECT * FROM {tablename} WHERE store_id = %s", (int(TENANT_A),))
                assert len(cur.fetchall()) == 0
                
                # Tenter de modifier les données de A en étant B
                cur.execute(f"UPDATE {tablename} SET store_id = %s WHERE store_id = %s", (int(TENANT_B), int(TENANT_A)))
                assert cur.rowcount == 0
                
                conn.rollback()
    except Exception as e:
        pytest.fail(f"Erreur isolation sur {tablename}: {e}")

def test_no_unprotected_tenant_table(rls_status: dict, policy_status: dict) -> None:
    rows = _fetch("SELECT c.relname AS tablename FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attname = 'store_id' AND a.attnum > 0 AND NOT a.attisdropped")
    tables_with_store_id = {r["tablename"] for r in rows}
    EXCLUDED_TABLES = {
        "users", "tenant_billing_profiles", "tenant_ai_usage_ledger", "store_blueprints",
        "media_uploads", "knowledge_chunks", "human_handoffs", "gdpr_audit_log",
        "failed_tasks", "emotion_alerts", "conversation_summaries", "conversation_memories"
    }
    unprotected = [tbl for tbl in tables_with_store_id if tbl not in EXCLUDED_TABLES and (not rls_status.get(tbl, {}).get("rowsecurity") or not policy_status.get(tbl))]
    assert not unprotected, f"Tables sans RLS: {unprotected}"
