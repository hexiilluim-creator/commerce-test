# Bloc 4 : Qualité et Couverture de Tests — Applied

Ce document trace les modifications faites pour clore le **Bloc 4** du guide
`Guide_de_Finalisation_et_Correction___AutoCommerce.md`.

Statut cible : **Enterprise Production Ready**.

---

## ✅ Tâche 1 — Test d'accès cross-tenant (Store B → Store A → 403)

**Fichier** : `api-server/tests/test_security_multitenant.py`

Ajout de la classe `TestCrossTenantAccessForbidden` avec **10 tests** couvrant :

| Test | Vérifie |
|---|---|
| `test_store_b_jwt_carries_store_b_id_only` | Le JWT du Store B ne peut pas prétendre être Store A |
| `test_store_b_cannot_read_store_a_orders` | SELECT Orders filtré par `store_id` du JWT |
| `test_direct_store_a_id_in_url_is_overridden_by_jwt` | `/stores/1/...` avec JWT B → 403 |
| `test_store_b_cannot_write_to_store_a_products` | POST avec `store_id` forgé dans le body ignoré |
| `test_store_b_cannot_delete_store_a_conversation` | DELETE conversation d'un autre tenant → 403 |
| `test_store_b_read_operation_returns_403_not_empty_list` | Politique 403 (pas 200 + `[]`) — évite fuite d'existence |
| `test_super_admin_can_access_any_store` | Seul `super_admin` peut traverser les tenants |
| `test_store_b_cannot_read_store_a_invoices` | Extension aux Invoices |
| `test_no_leak_via_pagination_cursor` | Pas de contournement via `?after_id=` |
| `test_forbidden_response_shape_is_stable` | Réponse 403 sans détail sensible |

---

## ✅ Tâche 2 — Mocks complets pour services tiers

**Fichier** : `api-server/tests/conftest.py`

- Nouvelles variables d'environnement de test : `STRIPE_API_KEY`, `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, `WHATSAPP_ACCESS_TOKEN`,
  `WHATSAPP_PHONE_NUMBER_ID`.
- **Mocks canoniques** utilisables directement dans un test :
  - `mock_whatsapp_client` — `_WhatsAppMockClient` (send_message, send_template,
    upload_media, mark_as_read, get_media_url).
  - `mock_stripe_api` — `_StripeMockAPI` (create_checkout_session,
    construct_webhook_event avec vérif de signature simulée).
  - `mock_openai_client` — `_OpenAIMockClient` (chat_completion, embedding, moderate).
- **Patch global `httpx.AsyncClient` / `httpx.Client`** via la fixture
  `mock_third_party_services` (autouse=True, scope=session) :
  toute requête sortante vers `graph.facebook.com`, `api.stripe.com`,
  `api.openai.com`, `api.anthropic.com`, `api.deepseek.com`, `sendgrid.*`
  reçoit une réponse plausible sans hit réseau.

Résultat : la suite de tests s'exécute même sans clé API réelle et sans internet.

---

## ✅ Tâche 3 — Load test pour `TenantMiddleware` (≤ 5 ms)

**Nouveau fichier** : `api-server/tests/load/test_tenant_middleware_latency.py`

Trois benchmarks :

1. **`test_jwt_decode_latency_under_5ms_p95`** — mesure le décodage JWT pur
   sur 1 000 itérations, assert mean < 5 ms **et** P95 < 5 ms.
2. **`test_tenant_middleware_path_check_latency`** — vérifie que le check
   `_is_public` sur 6 chemins reste sous 5 ms au P95.
3. **`test_full_tenant_check_pipeline_latency`** — simule le pipeline complet
   `_is_public` + JWT decode + `current_tenant_id.set()` :
   mean < 5 ms, P95 < 5 ms, P99 < 10 ms.
4. **`test_tenant_middleware_benchmark`** — alias `pytest-benchmark` (skip si
   le plugin n'est pas installé) pour intégration CI.

Marqueur : `@pytest.mark.load` (skippé de la suite unitaire par défaut).

Exécution :
```bash
pytest -m load tests/load/test_tenant_middleware_latency.py -v
```

Ajout des marqueurs `load` et `benchmark` à `pytest.ini` (mode `--strict-markers`).

---

## ✅ Tâche 4 — Couverture `services/saas_billing.py` ≥ 45 %

**Fichier** : `api-server/tests/test_saas_billing.py`

**+15 nouveaux tests** ciblant les branches non couvertes :

- `get_plan_by_code` : plan connu / plan inconnu.
- `get_active_subscription` : store sans abonnement / avec abonnement actif.
- `_empty_subscription_overview` : structure canonique, pas de mutation partagée.
- **Stripe checkout** — 3 tests :
  - Erreur si `STRIPE_SECRET_KEY` vide.
  - Erreur si plan inconnu.
  - Succès : URL retournée non vide.
- **Stripe webhook** — 4 tests :
  - Erreur si `STRIPE_WEBHOOK_SECRET` vide.
  - Signature invalide → `ValueError`.
  - `checkout.session.completed` valide → abonnement activé en DB.
  - Event non géré (`customer.created`) → no-op sans exception.
- `_FALLBACK_PLANS` : unicité des codes, présence de `starter`, `rank` cohérent.
- `compute_subscription_price` — durée 6 mois, matrice plans × durées.

Techniques utilisées : `unittest.mock.patch.dict("sys.modules", {"stripe": fake_stripe})`
pour injecter un faux SDK Stripe sans dépendre du package réel.

---

## Validation Finale

Une fois les 4 blocs appliqués, exécuter :
```bash
ACK_MANUAL_ROUNDTRIP=1 bash scripts/preflight_go_v25.sh
```

Wording officiel attendu en cas de succès :
> **Enterprise release approved.**

---

## Fichiers modifiés / créés

| Chemin | Type |
|---|---|
| `api-server/tests/conftest.py` | Modifié (mocks + fixtures) |
| `api-server/tests/test_security_multitenant.py` | Modifié (classe cross-tenant) |
| `api-server/tests/test_saas_billing.py` | Modifié (+15 tests) |
| `api-server/tests/load/test_tenant_middleware_latency.py` | **Nouveau** |
| `api-server/pytest.ini` | Modifié (markers `load`, `benchmark`) |
| `CHANGES_BLOC4.md` | **Nouveau** (ce document) |
