"""tests/test_llm_stub.py — Plan E — AI / ML helper tests.

These run without network access and without a DB: they exercise the pure
functions in services/llm_stub.py and services/loyalty_ia_service.py.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import UTC, datetime, timedelta, timezone

from services.llm_stub import (
    LLMConfig,
    generate_bullets,
    generate_text,
    seo_score,
    translate,
)
from services.loyalty_ia_service import (
    compute_rfm,
    personalize_reward,
    predict_churn,
    recommend_products,
    stable_model_version,
)
from services.restocking_service import (
    eoq,
    fft_lite_seasonality,
    holt_winters_forecast,
    linear_trend,
    residual_std,
    safety_stock,
)


def test_generate_text_is_deterministic():
    cfg = LLMConfig(seed="abc")
    assert generate_text("hello", max_chars=120, cfg=cfg) == generate_text("hello", max_chars=120, cfg=cfg)


def test_generate_text_respects_max_chars():
    out = generate_text("x" * 50, max_chars=50)
    assert len(out) <= 50


def test_generate_bullets_returns_n():
    bullets = generate_bullets("anything", n=6)
    assert len(bullets) == 6
    assert all(isinstance(b, str) and b for b in bullets)


def test_seo_score_with_ideal_title():
    s = seo_score("My Product Title That Is The Right Length", "A" * 120, ["product", "title"])
    assert 70 <= s <= 100


def test_seo_score_zero_for_missing():
    assert seo_score("", "", []) == 0


def test_translate_prefixes_locale_and_keeps_glossary():
    out = translate("Buy AutoCommerce today", "es", {"AutoCommerce": "AutoCommerce"})
    assert out.startswith("[es] ")
    assert "AutoCommerce" in out


# ─── Predictive Restocking pure helpers ────────────────────────────────────

def test_holt_winters_short_series_falls_back_to_mean():
    series = [10.0, 12.0, 11.0, 9.0]
    fc = holt_winters_forecast(series, horizon=5)
    assert len(fc) == 5
    assert all(x >= 0 for x in fc)


def test_holt_winters_long_series_handles_seasonality():
    series = [10 + (i % 7) for i in range(60)]
    fc = holt_winters_forecast(series, horizon=14)
    assert len(fc) == 14


def test_seasonality_decomposes_known_profile():
    series = [10 if i % 2 == 0 else 20 for i in range(28)]
    s = fft_lite_seasonality(series, period=7)
    assert set(s.keys()) == {1, 2, 3, 4, 5, 6, 7}


def test_linear_trend_positive_for_linear_series():
    assert linear_trend([1, 2, 3, 4, 5]) > 0


def test_safety_stock_grows_with_lead_time():
    a = safety_stock(5.0, 7)
    b = safety_stock(5.0, 30)
    assert b > a


def test_eoq_grows_with_demand():
    assert eoq(1000) > eoq(100)


# ─── Loyalty IA pure helpers ───────────────────────────────────────────────

def test_rfm_new_customer():
    r = compute_rfm(7, [])
    assert r.segment == "new"
    assert r.frequency == 0


def test_rfm_classifies_active_customer():
    now = datetime.now(UTC)
    orders = [(now - timedelta(days=i * 10), 50 + i) for i in range(6)]
    r = compute_rfm(1, orders, now=now)
    assert r.frequency == 6
    assert r.segment in {"champions", "loyal", "new"}


def test_personalize_respects_cooldown():
    now = datetime.now(UTC)
    rfm = compute_rfm(99, [(now - timedelta(days=i * 30), 100) for i in range(3)])
    eligible = [
        {"kind": "coupon", "value": 5, "id": 1},
        {"kind": "coupon", "value": 10, "id": 2},
        {"kind": "gift", "value": 20, "id": 3},
    ]
    last = {"coupon": now - timedelta(days=2)}
    cooldown = {"coupon": 7, "gift": 30}
    choice = personalize_reward(
        rfm=rfm, eligible_rewards=eligible,
        cooldown_per_kind=cooldown, last_rewards_by_kind=last, now=now,
    )
    assert choice is not None
    assert choice["kind"] in {"gift"}  # coupon is on cooldown


def test_churn_score_in_range():
    now = datetime.now(UTC)
    rfm = compute_rfm(5, [(now - timedelta(days=45), 100), (now - timedelta(days=10), 60)])
    score, band, drivers = predict_churn(
        rfm=rfm, days_since_last_reward=15,
        support_tickets_30d=0, avg_orders_per_month=2.0,
    )
    assert 0.0 <= score <= 1.0
    assert band in {"low", "medium", "high"}
    assert "recency_days" in drivers


def test_recommend_excludes_out_of_stock():
    out = recommend_products(
        customer_purchase_skus=["A"],
        cooccurrence={"A": {"B": 5, "C": 1}},
        catalog_skus=["A", "B", "C"],
        out_of_stock={"C"},
        top_n=3,
    )
    skus = [r["sku"] for r in out]
    assert "C" not in skus
    assert "B" in skus


def test_stable_model_version_changes_with_params():
    a = stable_model_version("churn", {"w": 1})
    b = stable_model_version("churn", {"w": 2})
    assert a != b
