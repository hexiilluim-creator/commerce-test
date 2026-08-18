"""0060_plan_limits_multi_duration_pricing

P1.5 — `services/saas_billing.py` (`ensure_default_saas_plans`,
`compute_subscription_price`, `_FALLBACK_PLANS`) a toujours attendu 3
colonnes de tarification multi-durée sur `plan_limits` :
`price_3months_dt`, `price_6months_dt`, `price_12months_dt`. La migration
0027 qui a créé la table ne les a jamais ajoutées (seuls `price_monthly_dt`/
`price_monthly_usd`/`price_annual_dt`/`price_annual_usd` existent) — un
décalage schéma/code pré-existant, jamais détecté car
`ensure_default_saas_plans` avale silencieusement l'exception PostgreSQL
`UndefinedColumnError` qui en résulte (voir le fix de rollback en 0059/P1.4 :
sans lui, l'erreur bloquait aussi la session pour les requêtes suivantes ;
avec lui, elle était juste masquée en log — les deux versions cachaient le
vrai problème).

Découvert en croisant un correctif tiers (`security_overlay/models.py`,
nouvelle classe ORM `PlanLimits` ajoutée pour les besoins des tests SQLite)
avec le schéma Postgres réel de la migration 0027 : la classe ORM déclarait
ces 3 colonnes comme si elles existaient déjà, ce qui a mis en évidence
qu'elles manquaient réellement côté Postgres.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0060_plan_limits_multi_duration_pricing"
down_revision = "0059_extend_rls_full_tenant_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("plan_limits"):
        return  # table pas encore créée (ordre de migration atypique) — no-op

    existing_columns = {c["name"] for c in insp.get_columns("plan_limits")}

    for col_name in ("price_3months_dt", "price_6months_dt", "price_12months_dt"):
        if col_name not in existing_columns:
            op.add_column(
                "plan_limits",
                sa.Column(col_name, sa.Float(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("plan_limits"):
        return

    existing_columns = {c["name"] for c in insp.get_columns("plan_limits")}
    for col_name in ("price_3months_dt", "price_6months_dt", "price_12months_dt"):
        if col_name in existing_columns:
            op.drop_column("plan_limits", col_name)
