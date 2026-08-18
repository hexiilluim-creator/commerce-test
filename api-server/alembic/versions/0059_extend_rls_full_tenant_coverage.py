"""0059_extend_rls_full_tenant_coverage

P1.2 — Corrige un trou de sécurité RLS réel : la migration 0058 n'activait
Row-Level-Security que sur 5 tables codées en dur (orders, products,
customers, audit_logs, credit_events). Toute table multi-tenant ajoutée
depuis (Plan B2B, Loyalty IA, Predictive Restocking, Visual Builder,
Omnicall Enterprise, SaaS overlay, etc.) n'avait donc AUCUNE policy RLS —
seul le filtrage applicatif protégeait l'isolation tenant sur ces tables,
sans défense en profondeur.

Découvert lors d'un audit de déploiement (Manus, juillet 2026) qui a dû
appliquer un correctif RLS manuel en environnement de test faute de
migration correspondante dans le dépôt. Manus a signalé 2 tables oubliées
(customer_identities, contact_endpoints) après une première passe de cette
migration. En creusant plus large — un scan direct de `op.create_table()`
sur TOUTES les migrations plutôt qu'un scan des seules classes ORM
Python (qui ne couvrent pas les tables gérées en SQL Core pur) — 20 tables
supplémentaires sont apparues avec un `store_id`/`tenant_id` non protégé.
Cette révision couvre la liste complète, vérifiée table par table.

Trois catégories :
  1. Tables avec une colonne store_id directe -> policy standard.
  2. Tables avec une colonne tenant_id (même sémantique que store_id,
     FK vers stores.id, juste un nom différent selon le module) -> même
     policy, sur tenant_id.
  3. Tables enfants sans colonne de tenant propre, isolées via une
     jointure : visual_build_assets/visual_build_reviews (-> build_id ->
     visual_builds.store_id) et password_reset_tokens (-> user_id ->
     users.store_id).

`stores` (table racine du tenant), `blueprints`, `saas_plans`,
`plan_limits`, `credit_top_up_packs` sont volontairement exclues : ce sont
des catalogues globaux/plateforme sans colonne de tenant, RLS non
applicable.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0059_extend_rls_full_tenant_coverage"
down_revision = "0058_enforce_rls_and_harden_credit_events"
branch_labels = None
depends_on = None


# Tables avec une colonne store_id directe.
_DIRECT_STORE_ID_TABLES = (
    # models/database.py
    "users",
    "product_variants",
    "whatsapp_messages",
    "store_phone_mappings",
    "store_social_mappings",
    "conversation_logs",
    "business_configs",
    "services",
    "availability_rules",
    "availability_exceptions",
    "appointments",
    "social_post_configs",
    "social_posts",
    "payment_links",
    "tax_rates",
    "tax_exemptions",
    "campaigns",
    "promotions",
    "promotion_rules",
    "coupons",
    "promotion_usage",
    "accounting_documents",
    "expenses",
    # models/b2b_portal.py
    "company_accounts",
    "company_users",
    "pricing_rules",
    "b2b_orders",
    "b2b_invoices",
    # models/loyalty_ia.py
    "segment_definitions",
    "customer_segment_members",
    "loyalty_recommendations",
    "loyalty_churn_scores",
    "loyalty_ia_model_versions",
    # models/predictive_restocking.py
    "restock_forecasts",
    "restock_alerts",
    "restock_suggestions",
    "restock_seasonality",
    # models/visual_builder.py
    "visual_builds",
    "visual_build_history",
    # alembic/versions/0010_overlay_billing_orchestrator.py
    "tenant_billing_profiles",
    "tenant_ai_usage_ledger",
    # alembic/versions/0019_expenses_and_dlq.py
    "failed_tasks",
    # alembic/versions/0023_s3_upload_tracking.py
    "media_uploads",
    # alembic/versions/0030_customer_identity_omnichannel.py — signalées par
    # l'audit Manus (juillet 2026), confirmées ici et ajoutées.
    "customer_identities",
    "contact_endpoints",
    "knowledge_chunks",
    # alembic/versions/0034_enterprise_omnicall.py
    "conversation_memories",
    "human_handoffs",
    "conversation_summaries",
    "emotion_alerts",
    # alembic/versions/0037_rgpd_data_retention.py
    "gdpr_audit_log",
    # alembic/versions/0052_add_blueprints_tables.py
    "store_blueprints",
)

# Tables avec tenant_id (même sémantique que store_id, FK -> stores.id).
_TENANT_ID_TABLES = (
    # alembic/versions/0012_saas_overlay_runtime.py
    "saas_subscriptions",
    "monthly_usage_snapshots",
    "ai_usage_events",
    "workflow_events",
    # alembic/versions/0027_maghreb_saas_plans.py
    "tenant_usage",
    "credit_ledger",
    # alembic/versions/0028_subscription_durations.py
    "tenant_subscriptions",
)

# Tables enfants sans colonne de tenant propre : isolation via jointure sur
# la table parente qui, elle, porte store_id.
_JOIN_POLICY_TABLES = {
    "visual_build_assets": ("build_id", "visual_builds"),
    "visual_build_reviews": ("build_id", "visual_builds"),
    "password_reset_tokens": ("user_id", "users"),
}


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(table)


def _enable_direct_policy(table: str, column: str = "store_id") -> None:
    policy = f"tenant_isolation_{table}"
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {policy} ON {table}
            USING (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR {column} = NULLIF(current_setting('app.current_tenant_id', true), '')::int
            )
            WITH CHECK (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR {column} = NULLIF(current_setting('app.current_tenant_id', true), '')::int
            )
            """
        )
    )


def _enable_join_policy(table: str, fk_column: str, parent_table: str) -> None:
    policy = f"tenant_isolation_{table}"
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {policy} ON {table}
            USING (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR {fk_column} IN (
                    SELECT id FROM {parent_table}
                    WHERE store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                )
            )
            WITH CHECK (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR {fk_column} IN (
                    SELECT id FROM {parent_table}
                    WHERE store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                )
            )
            """
        )
    )


def upgrade() -> None:
    if not _is_postgresql():
        return  # RLS est une fonctionnalité PostgreSQL — no-op sur SQLite (tests)

    for table in _DIRECT_STORE_ID_TABLES:
        if _table_exists(table):
            _enable_direct_policy(table, "store_id")

    for table in _TENANT_ID_TABLES:
        if _table_exists(table):
            _enable_direct_policy(table, "tenant_id")

    for table, (fk_column, parent_table) in _JOIN_POLICY_TABLES.items():
        if _table_exists(table) and _table_exists(parent_table):
            _enable_join_policy(table, fk_column, parent_table)


def downgrade() -> None:
    if not _is_postgresql():
        return

    all_tables = (
        list(_DIRECT_STORE_ID_TABLES) + list(_TENANT_ID_TABLES) + list(_JOIN_POLICY_TABLES)
    )
    for table in all_tables:
        if _table_exists(table):
            policy = f"tenant_isolation_{table}"
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
