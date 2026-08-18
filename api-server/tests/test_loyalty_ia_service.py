"""tests/test_loyalty_ia_service.py — Tests pour services/loyalty_ia_service.py (Plan E3).

BUG#10 FIX: ce module (186 lignes) était à 0% de couverture de tests.
Fonctions pures et déterministes — testables sans fixture DB.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from services.loyalty_ia_service import (
    RFMResult,
    compute_rfm,
    personalize_reward,
    predict_churn,
    recommend_products,
    stable_model_version,
)

# ─── compute_rfm ────────────────────────────────────────────────────────────

def test_compute_rfm_happy_path():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    orders = [
        (now - timedelta(days=5), 100.0),
        (now - timedelta(days=20), 50.0),
        (now - timedelta(days=40), 75.0),
    ]
    result = compute_rfm(customer_id=1, orders=orders, now=now)
    assert isinstance(result, RFMResult)
    assert result.recency_days == 5
    assert result.frequency == 3
    assert result.monetary == 225.0
    assert result.segment in {"champions", "loyal", "at_risk", "hibernating", "new"}


def test_compute_rfm_edge_case_empty_orders():
    """Client sans aucune commande → segment 'new', scores plancher."""
    result = compute_rfm(customer_id=1, orders=[])
    assert result.recency_days == 9999
    assert result.frequency == 0
    assert result.monetary == 0.0
    assert result.segment == "new"


def test_compute_rfm_single_order():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    orders = [(now - timedelta(days=1), 200.0)]
    result = compute_rfm(customer_id=2, orders=orders, now=now)
    assert result.frequency == 1
    assert result.monetary == 200.0


def test_compute_rfm_negative_amounts_clamped():
    """Montants négatifs (remboursements) ne doivent pas faire planter monetary."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    orders = [(now - timedelta(days=1), -50.0), (now - timedelta(days=2), 100.0)]
    result = compute_rfm(customer_id=3, orders=orders, now=now)
    assert result.monetary == 100.0  # negative clamped to 0 in sum


# ─── recommend_products ─────────────────────────────────────────────────────

def test_recommend_products_happy_path():
    cooccurrence = {"sku-a": {"sku-b": 5, "sku-c": 2}}
    result = recommend_products(
        customer_purchase_skus=["sku-a"],
        cooccurrence=cooccurrence,
        catalog_skus=["sku-a", "sku-b", "sku-c"],
        out_of_stock=set(),
        top_n=2,
    )
    assert len(result) <= 2
    assert all("sku" in r and "score" in r for r in result)
    # sku-b should rank higher than sku-c (weight 5 > 2)
    if len(result) == 2:
        assert result[0]["sku"] == "sku-b"


def test_recommend_products_edge_case_empty_history():
    """Client sans historique d'achat → fallback popularité, pas de crash."""
    result = recommend_products(
        customer_purchase_skus=[],
        cooccurrence={},
        catalog_skus=["sku-x", "sku-y"],
        out_of_stock=set(),
        top_n=5,
    )
    assert isinstance(result, list)


def test_recommend_products_excludes_out_of_stock():
    cooccurrence = {"sku-a": {"sku-b": 10, "sku-c": 5}}
    result = recommend_products(
        customer_purchase_skus=["sku-a"],
        cooccurrence=cooccurrence,
        catalog_skus=["sku-a", "sku-b", "sku-c"],
        out_of_stock={"sku-b"},
        top_n=5,
    )
    skus = [r["sku"] for r in result]
    assert "sku-b" not in skus  # excluded — out of stock


def test_recommend_products_excludes_already_purchased():
    cooccurrence = {"sku-a": {"sku-b": 10}}
    result = recommend_products(
        customer_purchase_skus=["sku-a", "sku-b"],  # already owns sku-b
        cooccurrence=cooccurrence,
        catalog_skus=["sku-a", "sku-b"],
        out_of_stock=set(),
        top_n=5,
    )
    skus = [r["sku"] for r in result]
    assert "sku-b" not in skus


# ─── personalize_reward ──────────────────────────────────────────────────────

def test_personalize_reward_happy_path():
    rfm = RFMResult(5, 10, 500.0, 5, 5, 5, "champions")
    rewards = [
        {"kind": "cashback", "value": 10},
        {"kind": "coupon", "value": 5},
    ]
    result = personalize_reward(
        rfm=rfm,
        eligible_rewards=rewards,
        cooldown_per_kind={},
        last_rewards_by_kind={},
    )
    assert result is not None
    assert result["kind"] in {"cashback", "coupon"}


def test_personalize_reward_edge_case_no_eligible_rewards():
    """Aucune récompense éligible → retourne None, pas d'exception."""
    rfm = RFMResult(5, 10, 500.0, 5, 5, 5, "champions")
    result = personalize_reward(
        rfm=rfm,
        eligible_rewards=[],
        cooldown_per_kind={},
        last_rewards_by_kind={},
    )
    assert result is None


def test_personalize_reward_respects_cooldown():
    """Une récompense en période de cooldown ne doit pas être sélectionnée."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    rfm = RFMResult(5, 10, 500.0, 5, 5, 5, "champions")
    rewards = [{"kind": "cashback", "value": 100}]
    result = personalize_reward(
        rfm=rfm,
        eligible_rewards=rewards,
        cooldown_per_kind={"cashback": 30},
        last_rewards_by_kind={"cashback": now - timedelta(days=5)},  # within cooldown
        now=now,
    )
    assert result is None  # only reward is on cooldown


# ─── predict_churn ────────────────────────────────────────────────────────────

def test_predict_churn_happy_path():
    rfm = RFMResult(10, 5, 200.0, 4, 4, 4, "loyal")
    score, band, drivers = predict_churn(
        rfm,
        days_since_last_reward=10,
        support_tickets_30d=0,
        avg_orders_per_month=2.0,
    )
    assert 0.0 <= score <= 1.0
    assert band in {"low", "medium", "high"}
    assert "rfm_segment" in drivers


def test_predict_churn_edge_case_high_risk():
    """Client inactif depuis longtemps + tickets support → risque élevé."""
    rfm = RFMResult(120, 1, 50.0, 1, 1, 1, "hibernating")
    score, band, drivers = predict_churn(
        rfm,
        days_since_last_reward=200,
        support_tickets_30d=5,
        avg_orders_per_month=0.1,
    )
    assert band == "high"
    assert score >= 0.7


def test_predict_churn_invalid_input_negative_values_clamped():
    """Valeurs négatives (bug amont) ne doivent jamais produire un score hors [0,1]."""
    rfm = RFMResult(-5, -1, -100.0, 1, 1, 1, "new")
    score, band, drivers = predict_churn(
        rfm,
        days_since_last_reward=-10,
        support_tickets_30d=-1,
        avg_orders_per_month=-1.0,
    )
    assert 0.0 <= score <= 1.0
    assert band in {"low", "medium", "high"}


# ─── stable_model_version ─────────────────────────────────────────────────────

def test_stable_model_version_deterministic():
    """Mêmes paramètres → même version (idempotence pour le model registry)."""
    v1 = stable_model_version("churn", {"a": 1, "b": 2})
    v2 = stable_model_version("churn", {"b": 2, "a": 1})  # different order
    assert v1 == v2  # order-independent due to sorted(params.items())


def test_stable_model_version_different_params_different_version():
    v1 = stable_model_version("churn", {"a": 1})
    v2 = stable_model_version("churn", {"a": 2})
    assert v1 != v2
