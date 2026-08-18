"""0029_remove_byok_openai_columns — Supprime les colonnes BYOK OpenAI inutilisées

Revision ID: 0029_remove_byok_openai_columns
Revises: 0028_subscription_durations
Create Date: 2026-06-12

Contexte (CRIT-2 Audit CTO V14) :
  La migration 0022 avait créé les colonnes BYOK OpenAI (openai_api_key_enc,
  openai_byok_enabled, openai_model_override, openai_api_key_last4,
  openai_key_updated_at) dans la table stores.

  Depuis la décision architecture v14.1, le BYOK OpenAI est officiellement
  DÉSACTIVÉ. Tous les tenants utilisent les providers plateforme (DeepSeek +
  OpenAI gpt-4o-mini fallback). Les colonnes BYOK sont restées en base mais
  ne sont jamais lues ni écrites — dead code DB.

Problèmes que cette migration résout :
  1. Des clés API potentiellement soumises par des clients sont stockées chiffrées
     mais jamais utilisées, sans aucune notification.
  2. En cas de compromission de la base, les clés chiffrées sont exposées sans
     aucune justification fonctionnelle.
  3. L'incohérence entre le schéma et le code (BYOK commenté comme désactivé dans
     openai_resolver.py) crée de la confusion et un risque contractuel.

Scope de cette migration :
  - DROP : openai_api_key_enc, openai_api_key_last4, openai_byok_enabled,
           openai_model_override, openai_key_updated_at, ix_stores_byok_enabled
  - KEEP : extra_config (colonne JSON générique ajoutée dans 0022, toujours utile)
  - KEEP : colonnes social tokens (instagram_token_enc, facebook_token_enc,
           tiktok_token_enc) — ajoutées dans 0008, utilisées fonctionnellement
           pour les intégrations réseaux sociaux.

Procédure de déploiement :
  1. Avant la migration, identifier les tenants avec openai_byok_enabled = true :
       SELECT id, name FROM stores WHERE openai_byok_enabled = true;
  2. Notifier ces tenants que leur clé BYOK a été retirée (email de support).
  3. Exécuter : alembic upgrade head
  4. Vérifier que le démarrage de l'API est nominal (openai_resolver.py ne
     référence plus ces colonnes).

Réversibilité :
  Le downgrade recrée les colonnes vides (clés perdues — non récupérables).
  Prévoir un backup avant déploiement si la réversibilité est requise.
"""
import sqlalchemy as sa

from alembic import op

revision = "0029_remove_byok_openai_columns"
down_revision = "0028_subscription_durations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Étape 1 — Supprimer l'index BYOK (doit être fait avant le DROP COLUMN)
    op.drop_index("ix_stores_byok_enabled", table_name="stores")

    # Étape 2 — Supprimer les colonnes OpenAI BYOK
    # Ces colonnes ne sont plus lues ni écrites depuis la décision v14.1.
    # Elles contiennent potentiellement des clés API chiffrées de tenants qui
    # ont soumis une clé en croyant activer le BYOK — clés jamais utilisées.
    op.drop_column("stores", "openai_api_key_enc")
    op.drop_column("stores", "openai_api_key_last4")
    op.drop_column("stores", "openai_byok_enabled")
    op.drop_column("stores", "openai_model_override")
    op.drop_column("stores", "openai_key_updated_at")

    # Note: extra_config (ajoutée dans 0022) est intentionnellement conservée.
    # C'est une colonne JSON générique utile pour les futures intégrations.


def downgrade() -> None:
    """Recrée les colonnes BYOK (sans données — clés perdues).

    ATTENTION : un downgrade après un déploiement en production signifie que
    les clés API des tenants ne seront pas restaurées. Utiliser uniquement
    en cas de rollback d'urgence dans les premières minutes post-déploiement.
    """
    op.add_column("stores", sa.Column(
        "openai_key_updated_at", sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_model_override", sa.String(64), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_byok_enabled", sa.Boolean(),
        nullable=False, server_default=sa.text("false")
    ))
    op.add_column("stores", sa.Column(
        "openai_api_key_last4", sa.String(4), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_api_key_enc", sa.Text(), nullable=True
    ))
    op.create_index(
        "ix_stores_byok_enabled",
        "stores",
        ["openai_byok_enabled"],
    )
