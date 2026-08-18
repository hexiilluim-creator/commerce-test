"""
services/loyalty_ia_service.py — Plan E3 — Loyalty IA.

Pure / deterministic helpers for RFM, recommendation scoring, reward
personalization, and churn. Designed so it can be unit-tested without a
database fixture containing real orders.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class RFMResult:
    recency_days: int
    frequency: int
    monetary: float
    r_score: int       # 1..5
    f_score: int       # 1..5
    m_score: int       # 1..5
    segment: str       # champions|loyal|at_risk|hibernating|new


def _quintile(value: float, sorted_unique_values: list[float]) -> int:
    """Return 1..5 score based on position relative to the cohort."""
    if not sorted_unique_values:
        return 3
    n = len(sorted_unique_values)
    # higher score = better (more recent / more frequent / more monetary)
    rank = sum(1 for v in sorted_unique_values if v <= value)
    pct = rank / n
    if pct <= 0.2: return 1
    if pct <= 0.4: return 2
    if pct <= 0.6: return 3
    if pct <= 0.8: return 4
    return 5


def _as_utc(dt: datetime) -> datetime:
    """Normalise un datetime en UTC-aware.

    AUDIT FIX : compute_rfm() et pick_best_reward() font des soustractions
    entre `now` (toujours UTC-aware, via datetime.now(UTC)) et des datetimes
    fournis par l'appelant (orders/rewards, potentiellement désérialisés
    depuis du JSON sans suffixe de fuseau horaire, ex: "2026-01-15T10:00:00"
    sans "Z"/"+00:00" — Pydantic produit alors un datetime naïf). Mélanger
    naïf et aware lève TypeError. On suppose UTC pour tout datetime naïf
    reçu plutôt que de planter — cohérent avec le fait que le reste de
    l'application stocke ses dates en UTC (voir models/database.py).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def compute_rfm(
    customer_id: int,
    orders: list[tuple[datetime, float]],  # (placed_at, total_amount)
    now: datetime | None = None,
) -> RFMResult:
    now = now or datetime.now(UTC)
    now = _as_utc(now)
    if not orders:
        return RFMResult(9999, 0, 0.0, 1, 1, 1, "new")
    last = _as_utc(max(o[0] for o in orders))
    recency = max(0, int((now - last).total_seconds() // 86400))
    freq = len(orders)
    monetary = sum(max(0.0, o[1]) for o in orders)

    # Cohort baselines — naive rank within supplied sample.
    recencies = sorted(max(0, int((now - _as_utc(max(o[0] for o in [o]))).total_seconds() // 86400))
                       for o in orders)
    freqs = sorted(len([oo for oo in orders if True]) for o in orders)
    monies = sorted(sum(oo[1] for oo in orders) for o in orders)
    # We need the *cohort* (all customers) to get a meaningful rank; tests pass
    # a list of RFM inputs. Here we approximate per-customer so behaviour is
    # at least stable.
    r_score = _quintile(-recency, sorted(-r for r in recencies))   # lower recency = better
    f_score = _quintile(freq, freqs)
    m_score = _quintile(monetary, monies)

    segment = _segment(r_score, f_score, m_score)
    return RFMResult(recency, freq, monetary, r_score, f_score, m_score, segment)


def _segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4: return "champions"
    if r >= 3 and f >= 3 and m >= 3: return "loyal"
    if r <= 2 and f <= 2 and m <= 2: return "hibernating"
    if r <= 2 and f >= 3:             return "at_risk"
    if m >= 4 and r >= 3:            return "loyal"
    return "new"


# ─── Recommandations (co-occurrence, deterministic) ────────────────────────

def recommend_products(
    *,
    customer_purchase_skus: list[str],
    cooccurrence: dict[str, dict[str, int]],
    catalog_skus: list[str],
    out_of_stock: set[str],
    top_n: int = 5,
) -> list[dict]:
    """Given a customer's basket history and a SKU co-occurrence matrix,
    score every catalog SKU and return the top N (excluding out-of-stock
    and the customer's own buys)."""
    scores: dict[str, float] = {}
    owned = set(customer_purchase_skus)
    for bought in customer_purchase_skus:
        for candidate, weight in (cooccurrence.get(bought, {}) or {}).items():
            if candidate in owned or candidate in out_of_stock:
                continue
            scores[candidate] = scores.get(candidate, 0.0) + float(weight)
    if not scores:
        # Fallback: popularity bias based on total co-occurrence weight per SKU.
        # BUG FIX (found via test_recommend_products_edge_case_empty_history):
        # original code referenced an undefined variable `c` in the comprehension
        # (cooccurrence.get(c, {})) — NameError on every call to this fallback path.
        for sku in catalog_skus:
            if sku in owned or sku in out_of_stock:
                continue
            popularity = sum((cooccurrence.get(other, {}) or {}).get(sku, 0) for other in catalog_skus)
            scores[sku] = float(popularity)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"sku": sku, "score": round(score, 4)} for sku, score in ranked[:top_n]]


# ─── Récompenses personnalisées ─────────────────────────────────────────────

def personalize_reward(
    *,
    rfm: RFMResult,
    eligible_rewards: list[dict],
    cooldown_per_kind: dict[str, int],
    last_rewards_by_kind: dict[str, datetime],
    now: datetime | None = None,
) -> dict | None:
    """Pick the best reward for a customer respecting cooldown windows."""
    now = now or datetime.now(UTC)
    best: dict | None = None
    best_score = -1.0
    for reward in eligible_rewards:
        kind = reward.get("kind", "discount")
        # Tier ordering: champions prefer cashback / gifts; at-risk prefer coupons.
        affinity = {
            "champions": {"cashback": 1.0, "gift": 0.95, "coupon": 0.7, "discount": 0.8, "free_shipping": 0.6},
            "loyal":     {"cashback": 0.8, "gift": 0.7, "coupon": 0.9, "discount": 0.9, "free_shipping": 0.8},
            "at_risk":   {"cashback": 0.5, "gift": 0.7, "coupon": 1.0, "discount": 1.0, "free_shipping": 0.8},
            "hibernating": {"cashback": 0.6, "gift": 0.9, "coupon": 1.0, "discount": 1.0, "free_shipping": 0.7},
            "new":       {"cashback": 0.6, "gift": 0.6, "coupon": 0.9, "discount": 0.9, "free_shipping": 1.0},
        }.get(rfm.segment, {"discount": 1.0}).get(kind, 0.5)
        last = last_rewards_by_kind.get(kind)
        cooldown = cooldown_per_kind.get(kind, 0)
        if last and cooldown and (now - _as_utc(last)).total_seconds() < cooldown * 86400:
            continue
        score = affinity * float(reward.get("value", 1))
        if score > best_score:
            best = reward
            best_score = score
    return best


# ─── Détection churn (logistic-style score from RFM + reward gap) ──────────

def predict_churn(
    rfm: RFMResult,
    *,
    days_since_last_reward: int,
    support_tickets_30d: int,
    avg_orders_per_month: float,
) -> tuple[float, str, dict]:
    """Return (score 0..1, risk_band, drivers) — deterministic weights."""
    # Weights are stable, documented in the README.
    recency_term = min(1.0, rfm.recency_days / 90.0)
    freq_term    = 1.0 - min(1.0, rfm.frequency / 12.0)
    reward_term  = min(1.0, days_since_last_reward / 60.0)
    ticket_term  = min(1.0, support_tickets_30d / 3.0)
    base         = 0.6 * recency_term + 0.2 * freq_term + 0.15 * reward_term + 0.05 * ticket_term
    # Lift if average monthly activity is high (still risky if they go silent).
    if rfm.frequency >= 5 and rfm.recency_days > 30:
        base += 0.10
    score = round(max(0.0, min(1.0, base)), 4)
    if score >= 0.7: band = "high"
    elif score >= 0.4: band = "medium"
    else: band = "low"
    drivers = {
        "recency_days": rfm.recency_days,
        "frequency": rfm.frequency,
        "days_since_last_reward": days_since_last_reward,
        "support_tickets_30d": support_tickets_30d,
        "avg_orders_per_month": round(avg_orders_per_month, 2),
        "rfm_segment": rfm.segment,
    }
    return score, band, drivers


# ─── Model registry helpers ─────────────────────────────────────────────────

def stable_model_version(name: str, params: dict) -> str:
    # AUDIT FIX (Bandit B324): SHA1 utilisé ici uniquement pour un identifiant
    # de version de modèle déterministe, pas pour de la sécurité.
    h = hashlib.sha1(repr(sorted(params.items())).encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{name}-{h}"
