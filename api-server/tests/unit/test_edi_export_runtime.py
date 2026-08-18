"""Couverture fonctionnelle des exports EDI et de leurs validateurs."""
from decimal import Decimal

from services.edi_export import (
    AccountingEntry,
    ExportResult,
    _compute_checksum,
    _generate_export_path,
    _round_money,
    _safe_string,
    _to_decimal,
    _yield_chunks,
    validate_amounts,
    validate_vat,
    verify_writings,
)


def make_entry(**overrides):
    data = dict(
        entry_id="e1", journal_code="VT", journal_label="Ventes", document_number="F-1",
        document_date="2026-08-14", document_type="invoice", account_number="411000",
        account_label="Client", partner_code="C1", partner_label="Client 1", partner_vat="TN123",
        debit=Decimal("119.00"), credit=Decimal("0.00"), tax_rate=Decimal("0.19"),
        tax_amount=Decimal("22.61"), currency="TND", description="Vente", store_id=1,
        country_code="TN",
    )
    data.update(overrides)
    return AccountingEntry(**data)


def test_edi_helpers_convert_normalize_checksum_paths_and_chunks():
    assert _to_decimal(" 12.50 ") == Decimal("12.50")
    assert _to_decimal(3) == Decimal("3")
    assert _to_decimal("") == Decimal("0")
    assert _round_money(Decimal("1.235")) == Decimal("1.24")
    assert _safe_string("a\n\tb") == "a  b"
    assert len(_safe_string("x" * 600)) == 500
    assert _compute_checksum(b"abc") == "ba7816bf8f01cfea"
    path, filename = _generate_export_path(4, "fec", "tn")
    assert filename.startswith("edi_fec_4_TN_") and path.suffix == ".txt"
    entries = [make_entry(entry_id=str(i)) for i in range(3)]
    assert [len(chunk) for chunk in _yield_chunks(entries, 2)] == [2, 1]


def test_accounting_entry_and_results_are_serializable():
    entry = make_entry()
    payload = entry.as_dict()
    assert payload["debit"] == "119.00" and payload["country_code"] == "TN"
    result = ExportResult("csv", "x.csv", __import__("pathlib").Path("/tmp/x.csv"), 10, 1, "now", "abc", "TN")
    assert result.as_dict()["format"] == "csv"


def test_validate_amounts_reports_balanced_and_invalid_entries():
    balanced = [make_entry(debit=Decimal("119.00")), make_entry(entry_id="e2", document_number="F-2", debit=Decimal("0"), credit=Decimal("119.00"), tax_amount=Decimal("0"))]
    valid = validate_amounts(balanced)
    assert valid.is_valid and valid.total_debit == Decimal("119.00") and valid.total_credit == Decimal("119.00")
    invalid = validate_amounts([make_entry(debit=Decimal("-1"), credit=Decimal("0"), tax_amount=Decimal("-1"))])
    assert invalid.is_valid is False and invalid.errors


def test_validate_vat_covers_supported_unknown_and_invalid_rates():
    assert validate_vat([make_entry()], "TN").is_valid
    invalid = validate_vat([make_entry(tax_rate=Decimal("0.99"))], "TN")
    assert invalid.is_valid is False
    unknown = validate_vat([make_entry()], "XX")
    assert unknown.is_valid and unknown.warnings


def test_verify_writings_detects_duplicates_missing_fields_bad_date_and_warnings():
    first = make_entry()
    duplicate = make_entry(entry_id="e2")
    duplicate.document_number = "F-1"
    bad = make_entry(entry_id="e3", document_number="F-3", document_date="not-a-date", account_number="", document_type="other")
    result = verify_writings([first, duplicate, bad])
    assert result.is_valid is False
    assert any("date invalide" in err for err in result.errors)
    assert any("document_number" in warning for warning in result.warnings)
    assert any("type de document inconnu" in warning for warning in result.warnings)



def test_country_exports_emit_files_and_regulatory_currency_warnings(tmp_path, monkeypatch):
    from services import edi_export as mod
    monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
    signed = make_entry(is_signed=True)
    tunisia = mod.export_tunisia(1, [signed], period_start="2026-01-01", period_end="2026-01-31")
    assert tunisia.path.exists() and tunisia.entry_count == 1
    assert "TN" in tunisia.country_compliance
    unsigned_foreign = make_entry(is_signed=False, currency="JPY")
    morocco = mod.export_morocco(2, [unsigned_foreign])
    algeria = mod.export_algeria(3, [unsigned_foreign])
    assert morocco.path.exists() and any("non-standard" in w for w in morocco.validation_warnings)
    assert algeria.path.exists() and any("non-standard" in w for w in algeria.validation_warnings)


def test_country_tax_regime_helpers_cover_known_and_unknown_rates():
    from services.edi_export import _determine_tax_regime_dz, _determine_tax_regime_ma
    assert _determine_tax_regime_ma(Decimal("0.20")) == "normal"
    assert _determine_tax_regime_ma(Decimal("0.123")) == "autre"
    assert _determine_tax_regime_dz(Decimal("0.19")) == "normal"
    assert _determine_tax_regime_dz(Decimal("0.123")) == "autre"
