from __future__ import annotations

import pytest

from security_overlay import plan_catalog as pc


def test_plan_lookup_known_and_unknown_codes():
    assert pc.get_plan_spec("business").price_monthly == 29.99
    assert pc.get_plan_spec("missing") is None
    assert "crm.advanced" in pc.get_plan_spec("enterprise").features


def test_gold_activation_is_fail_closed_by_default(monkeypatch):
    monkeypatch.delenv("GOLD_PLAN_PUBLIC", raising=False)
    assert pc.is_gold_plan_activation_allowed() is False
    with pytest.raises(ValueError, match="gold"):
        pc.assert_plan_activation_allowed("gold")
    pc.assert_plan_activation_allowed("business")


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_gold_activation_accepts_explicit_public_flag(monkeypatch, value):
    monkeypatch.setenv("GOLD_PLAN_PUBLIC", value)
    assert pc.is_gold_plan_activation_allowed() is True
    pc.assert_plan_activation_allowed("gold")


def test_price_duration_discounts_and_unknowns():
    assert pc.get_price_for_duration("business", "monthly") == 29.99
    assert pc.get_price_for_duration("business", "3months") == round(29.99 * 3 * 0.92, 2)
    assert pc.get_price_for_duration("business", "6months") == round(29.99 * 6 * 0.85, 2)
    assert pc.get_price_for_duration("business", "12months") == round(29.99 * 12 * 0.78, 2)
    assert pc.get_price_for_duration("business", "unknown") == 29.99
    assert pc.get_price_for_duration("missing", "monthly") == 0.0


def test_currency_catalog_selection_is_case_insensitive():
    assert pc.get_plan_catalog_for_currency("eur") is pc.PLAN_CATALOG_EUR
    assert pc.get_plan_catalog_for_currency("USD") is pc.PLAN_CATALOG_EUR
    assert pc.get_plan_catalog_for_currency("TND") is pc.PLAN_CATALOG
    assert pc.get_plan_catalog_for_currency("mad") is pc.PLAN_CATALOG


def test_currency_topup_pack_selection():
    assert pc.get_top_up_packs_for_currency("EUR") is pc.CREDIT_TOP_UP_PACKS_EUR
    assert pc.get_top_up_packs_for_currency("GBP") is pc.CREDIT_TOP_UP_PACKS_EUR
    assert pc.get_top_up_packs_for_currency("TND") is pc.CREDIT_TOP_UP_PACKS
    assert all(pack.currency == "EUR" for pack in pc.get_top_up_packs_for_currency("USD"))
    assert all(pack.currency == "TND" for pack in pc.get_top_up_packs_for_currency("DZD"))


def test_catalog_contains_expected_public_and_hidden_plans():
    assert set(("free", "starter", "business", "premium", "pro_whatsapp", "pro", "enterprise", "gold")) <= set(pc.PLAN_CATALOG)
    assert pc.PLAN_CATALOG["gold"].is_public is False
    assert pc.PLAN_CATALOG["free"].price_monthly == 0.0
    assert pc.PLAN_CATALOG_EUR["enterprise_eur"].price_monthly == 299.0


def test_duration_options_and_pack_shapes_are_complete():
    assert pc.DURATION_OPTIONS == ["monthly", "3months", "6months", "12months"]
    assert len(pc.CREDIT_TOP_UP_PACKS) == 4
    assert len(pc.CREDIT_TOP_UP_PACKS_EUR) == 4
    assert {pack.currency for pack in pc.CREDIT_TOP_UP_PACKS} == {"TND"}
    assert {pack.currency for pack in pc.CREDIT_TOP_UP_PACKS_EUR} == {"EUR"}
