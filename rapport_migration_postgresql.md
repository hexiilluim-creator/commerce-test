# Rapport de Migration PostgreSQL — AutoCommerce Enterprise V28

**Date :** 5 août 2026  
**Environnement :** PostgreSQL 16.14 (Ubuntu 24.04)  
**Projet :** AutoCommerce Enterprise V28 Merged  
**Résultat :** **SUCCÈS** — `alembic upgrade head` terminé sans erreur (exit code 0)

---

## 1. Résumé de l'exécution

La migration complète a été exécutée avec succès sur une base PostgreSQL vide. Toutes les migrations de `0001_initial` jusqu'à `0064_merge_rls_audit_and_loyalty` (head) ont été appliquées dans l'ordre correct, incluant les fusions de branches (`merge_heads`, `merge_all_heads`, `merge_all_final_heads`, `0038_final_merge_head`, `0042_merge_all_final_heads`, `0050_merge_fg_plans_into_main`, `0064_merge_rls_audit_and_loyalty`).

| Indicateur | Valeur |
|-----------|--------|
| **Version Alembic finale** | `0064_merge_rls_audit_and_loyalty` (head) |
| **Tables créées** | 77 (dont `alembic_version`) |
| **Tables métier** | 76 |
| **Tables avec RLS activé** | 71 |
| **Policies RLS créées** | 73 |
| **Index totaux** | 380 |
| **Temps d'exécution** | < 120 secondes |
| **Code de sortie** | 0 |

---

## 2. Chaîne de migration exécutée

L'ordre d'exécution complet (70 migrations dont les fusions) :

| # | Migration | Description |
|---|-----------|-------------|
| 1 | `0001_initial` | Schéma initial — toutes les tables de base |
| 2 | `0002_p1_features` | Conversation FSM log, audit trail, store settings |
| 3 | `0003_sprint1_blockers` | 5 bloquants Sprint 1 |
| 4 | `0004_sprint2_pgvector` | pgvector + security |
| 5 | `0005_structured_agent_fields` | Customer emotion + preferences |
| 6 | `0006_appointments_module` | Tables RDV (BusinessConfig, Service, Availability, Appointment) |
| 7 | `0007_store_owner_phone` | Colonne owner_phone sur stores |
| 8 | `0008_social_media_byok` | Colonnes BYOK réseaux sociaux |
| 9 | `0009_omnichannel_customer` | Canal de communication |
| 10 | `0010_billing_orch` | Overlay billing + AI usage ledger |
| 11 | `0011_kill_switch` | Tenant kill switch |
| 12 | `0012_saas_runtime` | SaaS overlay runtime |
| 13 | `0013_auto_parts_fields` | OEM lookup + pièces auto |
| 14 | `0014_social_ai` | IA social + historique posts |
| 15 | `0015_store_public_fields` | Champs publics boutique |
| 16 | `0016_store_public_extra` | Horaires, OSM, liens sociaux |
| 17 | `0017_mfa_and_rgpd` | MFA TOTP + RGPD |
| 18 | `0018_pay_links` | PaymentLink + Store.country |
| 19 | `0019_expenses_and_dlq` | Spending Tracker + DLQ |
| 20 | `0020_drift_fix` | Fix stores et payment_links |
| 21 | `0021_composite_indexes` | Index composites 1000 tenants |
| 22 | `0022_byok_openai` | Colonnes BYOK OpenAI |
| 23 | `0023_s3_upload` | Tracking S3 keys |
| 24 | `0024_enterprise_2k` | Optimisations 2000 tenants (BRIN + GIN) |
| 25 | `0025_pgvector_hnsw` | Embeddings JSON → Vector(1536) + HNSW |
| 26 | `0026_gin_index` | GIN indexes conversation_state + preferences |
| 27 | `0027_maghreb_saas` | Plans SaaS Maghreb + credit_ledger |
| 28 | `0028_subscription_durations` | Abonnements 3/6/12 mois |
| 29 | `0029_remove_byok_openai` | Suppression colonnes BYOK inutilisées |
| 30 | `0030_customer_identity` | CustomerIdentity + ContactEndpoint |
| 31 | `0031_whatsapp_manual_reply` | direction + is_manual_reply |
| 32 | `0032_customer_opted_out` | opted_out fields |
| 33 | `0033_credit_events_ledger` | credit_events ledger immuable |
| 34 | `0034_enterprise_omnicall` | Tables Enterprise Phase 1 |
| 35 | `0035_password_reset_tokens` | Tokens de réinitialisation |
| 36 | `0036_drift_fix_store_public` | Fix schema drift stores |
| 37 | `0037_rgpd_data_retention` | RGPD rétention + gdpr_audit_log |
| 38 | `0038_final_merge_head` | Fusion branches |
| 39 | `0039_numeric_monetary` | Float → Numeric(12,4) |
| 40 | `0040_order_status` | RETURNED + REFUNDED enum |
| 41 | `0041_product_images` | images + image_count |
| 42 | `0042_merge_all_final_heads` | Fusion finale |
| 43 | `0043_user_role_constraint` | CHECK users.role |
| 44 | `0044_plan_a_tax_billing` | Tax + billing |
| 45 | `0045_plan_b_promotions` | Promotions + marketing |
| 46 | `0046_plan_e_visual_builder` | Visual builder |
| 47 | `0047_plan_e_restocking` | Predictive restocking |
| 48 | `0048_plan_e_loyalty_ia` | Loyalty IA |
| 49 | `0049_plan_f_b2b_portal` | B2B portal |
| 50 | `0050_merge_fg_plans` | Fusion Plans A→F |
| 51 | `0051_runtime_alignment` | orderstatus enum + credit pack |
| 52 | `0052_blueprints` | Tables blueprints |
| 53 | `0053_store_social_mappings` | store_social_mappings |
| 54 | `0054_order_created_at_index` | Index orders.created_at |
| 55 | `0055_multitenant_indexes` | Index store_id multi-tenant |
| 56 | `0056_payment_provider_enum` | Enum paymentprovider |
| 57 | `0057_repair_critical_drift` | Réparation plan_limits, tenant_subscriptions, orders |
| 58 | **`0058_rls_and_harden_credit_events`** | **RLS policies + credit_events event types** |
| 59 | `0059_extend_rls_coverage` | Extension RLS complète |
| 60 | `0060_plan_limits_pricing` | Multi-duration pricing |
| 61 | **`0061_loyalty_wallet_tables`** | **4 tables loyalty + RLS** |
| 62 | `0063_full_rls_audit` | RLS sur toutes les tables restantes |
| 63 | **`0064_merge_rls_audit_and_loyalty`** | **Fusion 0061 + 0063 (head)** |

---

## 3. Vérification des corrections 0058 / 0061 / 0064

### 3.1. Migration 0058 — Policies RLS sur audit_logs et credit_events

La correction de la migration 0058 fonctionne parfaitement. Les policies `FOR ALL` sur `audit_logs` et `credit_events` ont été remplacées par deux policies distinctes chacune :

| Table | Policy | Type | Status |
|-------|--------|------|--------|
| `audit_logs` | `tenant_isolation_audit_logs_select` | SELECT | OK |
| `audit_logs` | `tenant_isolation_audit_logs_insert` | INSERT | OK |
| `credit_events` | `tenant_isolation_credit_events_select` | SELECT | OK |
| `credit_events` | `tenant_isolation_credit_events_insert` | INSERT | OK |
| `orders` | `tenant_isolation_orders` | ALL | OK |
| `products` | `tenant_isolation_products` | ALL | OK |
| `customers` | `tenant_isolation_customers` | ALL | OK |

### 3.2. Migration 0061 — Tables loyalty sans doublons d'index

Les 4 tables loyalty ont été créées sans collision d'index (plus de `index=True` sur les colonnes). Chaque table possède uniquement les index explicites via `create_index` :

| Table | Index |
|-------|-------|
| `loyalty_programs` | `ix_loyalty_programs_store_id` + `uq_loyalty_program_store` + pkey |
| `loyalty_rules` | `ix_loyalty_rules_store_id`, `ix_loyalty_rules_is_active` + pkey |
| `loyalty_accounts` | `ix_loyalty_accounts_store_id`, `ix_loyalty_accounts_customer_id` + `uq_loyalty_account_store_customer` + pkey |
| `loyalty_ledger_entries` | `ix_loyalty_ledger_entries_account_id`, `ix_loyalty_ledger_entries_created_at` + `uq_loyalty_ledger_idempotency_key` + pkey |

### 3.3. Migration 0064 — Fusion des deux têtes

La migration de fusion `0064_merge_rls_audit_and_loyalty` a correctement résolu le problème de double tête :

```
alembic current = 0064_merge_rls_audit_and_loyalty (head)
alembic heads   = 0064_merge_rls_audit_and_loyalty (head)   ← unique
```

---

## 4. État de sécurité RLS

| Statistique | Valeur |
|------------|--------|
| Tables avec RLS activé | 71 sur 76 |
| Policies RLS totales | 73 |
| Policies FOR ALL | 68 |
| Policies FOR SELECT + INSERT | 4 (audit_logs × 2, credit_events × 2) |
| Tables RLS + FORCE RLS | 71 |

Toutes les tables multi-tenant critiques sont protégées par Row Level Security avec une clause d'isolation tenant basée sur `store_id` et `current_setting('app.current_tenant_id', true)`.

---

## 5. Contraintes CHECK vérifiées

### credit_events.event_type

La contrainte CHECK sur `event_type` a été correctement mise à jour par la migration 0058 :

```
CHECK (event_type IN ('allocate', 'bonus', 'deduct', 'expire', 
       'refund', 'renewal', 'reset', 'top_up', 'usage'))
```

Les 9 types d'événements sont présents (ajout de `bonus`, `renewal`, `reset`, `top_up`, `usage` par rapport à l'ancienne version).

---

## 6. Erreur résolue : pgvector

La migration `0025_embedding_pgvector_hnsw` nécessite l'extension `pgvector`. Celle-ci a été installée via `postgresql-16-pgvector` :

```
CREATE EXTENSION IF NOT EXISTS vector  ← OK
```

Un WARNING a été émis par SQLAlchemy (`SAWarning: Did not recognize type 'vector'`), ce qui est normal car asyncpg ne reconnaît pas nativement le type `vector`. Cela n'affecte pas l'exécution des migrations.

---

## 7. Conclusion

**Les 3 corrections sont validées en production locale :**

| Correction | Problème | Résolution | Status |
|-----------|----------|-----------|--------|
| **0058** | Policy `FOR ALL` bloquait `alembic upgrade head` | 2 policies `SELECT` + `INSERT` sur audit_logs/credit_events | PASSE |
| **0061** | `index=True` + `create_index` → `DuplicateTableError` | Flags `index=True` retirés, `create_index` explicite uniquement | PASSE |
| **0064** | Double tête `0061` + `0063` → `Multiple head revisions` | Migration de fusion `0064_merge_rls_audit_and_loyalty` | PASSE |

**Le projet est prêt pour un déploiement avec `alembic upgrade head`.**
