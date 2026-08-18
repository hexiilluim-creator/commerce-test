"""
tests/unit/test_edi_export.py — Tests unitaires complets pour services/edi_export.py.

Couverture :
    - Helpers (_to_decimal, _round_money, _safe_string, _compute_checksum, _yield_chunks)
    - Validation des montants (valide, négatif, déséquilibre, arrondi)
    - Validation TVA par pays (TN, MA, DZ, FR, inconnu)
    - Vérification des écritures (doublons, champs manquants, dates invalides)
    - Export FEC (format, BOM, header, données)
    - Export CSV (BOM UTF-8, chunks, totaux)
    - Export XML (structure, namespace, totals)
    - Export JSON (structure, validation, encoding)
    - Export Tunisie (CGI art. 18 compliance)
    - Export Maroc (ICE, régime fiscal)
    - Export Algérie (G50, CTCA)
    - export_edi() compatibilité API existante
    - Exceptions métier
    - Gestion gros volumes (chunks)
    - Gestion UTF-8 (accents, normalisation)
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

# Import du module testé
from services.edi_export import (
    CHUNK_SIZE,
    FEC_BOM,
    FEC_ENCODING,
    FEC_VERSION,
    TVA_RATES_DZ,
    TVA_RATES_FR,
    TVA_RATES_MA,
    TVA_RATES_TN,
    AccountingEntry,
    AmountValidationError,
    EDIExportError,
    EncodingError,
    ExportFormatError,
    ExportResult,
    ValidationError,
    ValidationResult,
    VATValidationError,
    VolumeExceededError,
    WritingVerificationError,
    _compute_checksum,
    _determine_tax_regime_dz,
    _determine_tax_regime_ma,
    _generate_export_path,
    _round_money,
    _safe_string,
    _to_decimal,
    _yield_chunks,
    export_algeria,
    export_csv,
    export_edi,
    export_fec,
    export_json,
    export_morocco,
    export_tunisia,
    export_xml,
    validate_amounts,
    validate_vat,
    verify_writings,
)

# ─── Fixture : crée une AccountingEntry valide ───────────────────────────────


@pytest.fixture
def valid_entry() -> AccountingEntry:
    """Crée une écriture comptable valide."""
    return AccountingEntry(
        entry_id="ENT-001",
        journal_code="VT",
        journal_label="Ventes",
        document_number="INV-2026-001",
        document_date="2026-01-15T10:30:00+00:00",
        document_type="invoice",
        account_number="707100",
        account_label="Ventes de marchandises",
        partner_code="CLI-001",
        partner_label="Client Alpha SARL",
        partner_vat="TN1234567890",
        debit=Decimal("1000.00"),
        credit=Decimal("0"),
        tax_rate=Decimal("0.19"),
        tax_amount=Decimal("190.00"),
        currency="TND",
        description="Vente pièces auto",
        store_id=1,
        country_code="TN",
        is_signed=True,
        signature_hash="abc123def456",
    )


@pytest.fixture
def paired_entries(valid_entry: AccountingEntry) -> list[AccountingEntry]:
    """Crée une paire débit/crédit équilibrée."""
    entry2 = AccountingEntry(
        entry_id="ENT-002",
        journal_code="VT",
        journal_label="Ventes",
        document_number="INV-2026-001",
        document_date="2026-01-15T10:30:00+00:00",
        document_type="invoice",
        account_number="411100",
        account_label="Clients",
        partner_code="CLI-001",
        partner_label="Client Alpha SARL",
        partner_vat="TN1234567890",
        debit=Decimal("0"),
        credit=Decimal("1000.00"),
        tax_rate=Decimal("0.19"),
        tax_amount=Decimal("190.00"),
        currency="TND",
        description="Vente pièces auto (contre-partie)",
        store_id=1,
        country_code="TN",
        is_signed=True,
        signature_hash="abc123def456",
    )
    return [valid_entry, entry2]


# ─── Helpers ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_to_decimal_from_decimal():
    """_to_decimal retourne le Decimal tel quel."""
    d = Decimal("42.50")
    assert _to_decimal(d) == d


@pytest.mark.unit
def test_to_decimal_from_int():
    """_to_decimal convertit int en Decimal."""
    assert _to_decimal(42) == Decimal("42")


@pytest.mark.unit
def test_to_decimal_from_float():
    """_to_decimal convertit float en Decimal."""
    assert _to_decimal(42.5) == Decimal("42.5")


@pytest.mark.unit
def test_to_decimal_from_string():
    """_to_decimal convertit string en Decimal."""
    assert _to_decimal("42.50") == Decimal("42.50")


@pytest.mark.unit
def test_to_decimal_from_empty_string():
    """_to_decimal retourne 0 pour une string vide."""
    assert _to_decimal("") == Decimal("0")


@pytest.mark.unit
def test_to_decimal_from_none():
    """_to_decimal retourne 0 pour None."""
    assert _to_decimal(None) == Decimal("0")


@pytest.mark.unit
def test_to_decimal_from_whitespace():
    """_to_decimal retourne 0 pour une string de whitespace."""
    assert _to_decimal("   ") == Decimal("0")


@pytest.mark.unit
def test_round_money():
    """_round_money arrondit à 2 décimales."""
    assert _round_money(Decimal("1.2345")) == Decimal("1.23")
    assert _round_money(Decimal("1.235")) == Decimal("1.24")
    assert _round_money(Decimal("1.225")) == Decimal("1.23")
    assert _round_money(Decimal("0.005")) == Decimal("0.01")


@pytest.mark.unit
def test_round_money_zero():
    """_round_money sur zéro retourne zéro."""
    assert _round_money(Decimal("0")) == Decimal("0.00")


@pytest.mark.unit
def test_safe_string_none():
    """_safe_string retourne '' pour None."""
    assert _safe_string(None) == ""


@pytest.mark.unit
def test_safe_string_accent():
    """_safe_string normalise les accents en NFC."""
    result = _safe_string("café")
    assert "caf" in result


@pytest.mark.unit
def test_safe_string_newlines():
    """_safe_string remplace les newlines."""
    result = _safe_string("ligne1\nligne2\ttab")
    assert "\n" not in result
    assert "\t" not in result


@pytest.mark.unit
def test_safe_string_truncation():
    """_safe_string tronque à 500 caractères."""
    long_str = "a" * 600
    assert len(_safe_string(long_str)) == 500


@pytest.mark.unit
def test_compute_checksum_deterministic():
    """_compute_checksum est déterministe."""
    data = b"test data"
    c1 = _compute_checksum(data)
    c2 = _compute_checksum(data)
    assert c1 == c2
    assert len(c1) == 16


@pytest.mark.unit
def test_compute_checksum_different_data():
    """_compute_checksum retourne des valeurs différentes pour des données différentes."""
    c1 = _compute_checksum(b"data1")
    c2 = _compute_checksum(b"data2")
    assert c1 != c2


@pytest.mark.unit
def test_yield_chunks_small_list():
    """_yield_chunks gère une liste plus petite que chunk_size."""
    entries = ["a", "b", "c"]
    chunks = list(_yield_chunks(entries, chunk_size=10))
    assert len(chunks) == 1
    assert chunks[0] == ["a", "b", "c"]


@pytest.mark.unit
def test_yield_chunks_exact_multiple():
    """_yield_chunks divise correctement les multiples exacts."""
    entries = ["a", "b", "c", "d"]
    chunks = list(_yield_chunks(entries, chunk_size=2))
    assert len(chunks) == 2
    assert chunks[0] == ["a", "b"]
    assert chunks[1] == ["c", "d"]


@pytest.mark.unit
def test_yield_chunks_large_list():
    """_yield_chunks divise une grande liste en chunks."""
    entries = list(range(2500))
    chunks = list(_yield_chunks(entries, chunk_size=1000))
    assert len(chunks) == 3
    assert len(chunks[0]) == 1000
    assert len(chunks[1]) == 1000
    assert len(chunks[2]) == 500


@pytest.mark.unit
def test_yield_chunks_empty_list():
    """_yield_chunks retourne aucun chunk pour une liste vide."""
    chunks = list(_yield_chunks([], chunk_size=10))
    assert len(chunks) == 0


@pytest.mark.unit
def test_generate_export_path():
    """_generate_export_path génère un chemin valide."""
    path, name = _generate_export_path(1, "json", "TN")
    assert path.suffix == ".json"
    assert "edi_json_1_TN_" in name


@pytest.mark.unit
def test_generate_export_path_fec():
    """_generate_export_path FEC utilise l'extension .txt."""
    path, name = _generate_export_path(1, "fec", "TN")
    assert path.suffix == ".txt"


# ─── Validation des montants ─────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_amounts_valid(paired_entries):
    """validate_amounts retourne valide pour des montants corrects."""
    result = validate_amounts(paired_entries)
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.entry_count == 2


@pytest.mark.unit
def test_validate_amounts_negative_debit():
    """validate_amounts détecte un débit négatif."""
    entry = AccountingEntry(
        entry_id="ENT-NEG", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("-100"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_amounts([entry])
    assert result.is_valid is False
    assert any("débit négatif" in e for e in result.errors)


@pytest.mark.unit
def test_validate_amounts_negative_credit():
    """validate_amounts détecte un crédit négatif."""
    entry = AccountingEntry(
        entry_id="ENT-NEG", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("-100"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_amounts([entry])
    assert result.is_valid is False
    assert any("crédit négatif" in e for e in result.errors)


@pytest.mark.unit
def test_validate_amounts_desequilibre():
    """validate_amounts détecte un déséquilibre débit/crédit."""
    entry1 = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_amounts([entry1])
    assert result.is_valid is False
    assert any("Déséquilibre" in e for e in result.errors)


@pytest.mark.unit
def test_validate_amounts_totals():
    """validate_amounts calcule correctement les totaux."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("500"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("95"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_amounts([entry])
    assert result.total_debit == Decimal("500.00")
    assert result.total_credit == Decimal("0.00")


@pytest.mark.unit
def test_validate_amounts_empty_list():
    """validate_amounts retourne valide pour une liste vide."""
    result = validate_amounts([])
    assert result.is_valid is True
    assert result.entry_count == 0


@pytest.mark.unit
def test_validate_amounts_as_dict():
    """ValidationResult.as_dict() retourne un dictionnaire sérialisable."""
    result = validate_amounts([])
    d = result.as_dict()
    assert "is_valid" in d
    assert "errors" in d
    assert "total_debit" in d


# ─── Validation TVA ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_vat_tn_valid(valid_entry):
    """validate_vat accepte les taux TVA tunisiens valides."""
    result = validate_vat([valid_entry], "TN")
    assert result.is_valid is True


@pytest.mark.unit
def test_validate_vat_tn_invalid_rate():
    """validate_vat rejette un taux TVA tunisien invalide."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.25"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_vat([entry], "TN")
    assert result.is_valid is False
    assert any("non autorisé" in e for e in result.errors)


@pytest.mark.unit
def test_validate_vat_ma_valid():
    """validate_vat accepte les taux TVA marocains valides."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="MA123",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.20"), tax_amount=Decimal("200"),
        currency="MAD", description="Test", store_id=1, country_code="MA",
    )
    result = validate_vat([entry], "MA")
    assert result.is_valid is True


@pytest.mark.unit
def test_validate_vat_dz_valid():
    """validate_vat accepte les taux TVA algériens valides."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="DZ123",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="DZD", description="Test", store_id=1, country_code="DZ",
    )
    result = validate_vat([entry], "DZ")
    assert result.is_valid is True


@pytest.mark.unit
def test_validate_vat_fr_valid():
    """validate_vat accepte les taux TVA français valides."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="FR123",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.20"), tax_amount=Decimal("200"),
        currency="EUR", description="Test", store_id=1, country_code="FR",
    )
    result = validate_vat([entry], "FR")
    assert result.is_valid is True


@pytest.mark.unit
def test_validate_vat_unknown_country():
    """validate_vat passe pour un pays inconnu avec warning."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="USD", description="Test", store_id=1, country_code="US",
    )
    result = validate_vat([entry], "US")
    assert result.is_valid is True
    assert any("inconnu" in w for w in result.warnings)


@pytest.mark.unit
def test_validate_vat_negative_rate():
    """validate_vat détecte un taux TVA négatif."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("-0.10"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = validate_vat([entry], "TN")
    assert result.is_valid is False
    assert any("négatif" in e for e in result.errors)


# ─── Vérification des écritures ──────────────────────────────────────────────


@pytest.mark.unit
def test_verify_writings_valid(paired_entries):
    """verify_writings valide des écritures correctes."""
    result = verify_writings(paired_entries)
    assert result.is_valid is True
    assert len(result.errors) == 0


@pytest.mark.unit
def test_verify_writings_duplicate_id():
    """verify_writings détecte les doublons d'entry_id."""
    entry1 = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    entry2 = AccountingEntry(
        entry_id="E1",  # Doublon !
        journal_code="VT", journal_label="Ventes",
        document_number="INV-002", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = verify_writings([entry1, entry2])
    assert result.is_valid is False
    assert any("Doublon" in e for e in result.errors)


@pytest.mark.unit
def test_verify_writings_missing_field():
    """verify_writings détecte un champ obligatoire manquant."""
    entry = AccountingEntry(
        entry_id="",  # Champ obligatoire vide !
        journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = verify_writings([entry])
    assert result.is_valid is False
    assert any("obligatoire" in e for e in result.errors)


@pytest.mark.unit
def test_verify_writings_invalid_date():
    """verify_writings détecte une date invalide."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="not-a-date",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = verify_writings([entry])
    assert result.is_valid is False
    assert any("date invalide" in e for e in result.errors)


@pytest.mark.unit
def test_verify_writings_unknown_doc_type():
    """verify_writings génère un warning pour un type de document inconnu."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="unknown_type", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = verify_writings([entry])
    assert result.is_valid is True
    assert any("inconnu" in w for w in result.warnings)


@pytest.mark.unit
def test_verify_writings_duplicate_doc_number_warning():
    """verify_writings génère un warning pour des document_number dupliqués."""
    entry1 = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-DUP", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    entry2 = AccountingEntry(
        entry_id="E2", journal_code="VT", journal_label="Ventes",
        document_number="INV-DUP", document_date="2026-01-02T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("0"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = verify_writings([entry1, entry2])
    assert result.is_valid is True
    assert any("déjà utilisé" in w for w in result.warnings)


# ─── Export FEC ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_fec_basic(paired_entries):
    """export_fec génère un fichier FEC valide."""
    result = export_fec(1, paired_entries, country="TN")
    assert result.format_name == "FEC"
    assert result.entry_count == 2
    assert result.size_bytes > 0
    assert result.path.exists()
    assert result.checksum


@pytest.mark.unit
def test_export_fec_has_bom():
    """export_fec commence par le BOM UTF-8."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_fec(1, [entry], country="TN")
    raw = result.path.read_bytes()
    assert raw[:3] == FEC_BOM


@pytest.mark.unit
def test_export_fec_has_header():
    """export_fec contient l'en-tête FEC avec les 18 colonnes."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_fec(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    lines = raw.split("\r\n")
    header = lines[0]
    assert "EcritureDate" in header
    assert "Debit" in header
    assert "Credit" in header
    assert header.count("|") == 17  # 18 colonnes = 17 séparateurs


@pytest.mark.unit
def test_export_fec_metadata():
    """export_fec retourne les métadonnées correctes."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_fec(1, [entry], country="TN")
    assert result.metadata["fec_version"] == FEC_VERSION
    assert result.country_compliance == "TN_FEC_v1.0"


# ─── Export CSV ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_csv_basic(paired_entries):
    """export_csv génère un fichier CSV valide."""
    result = export_csv(1, paired_entries, country="TN")
    assert result.format_name == "CSV"
    assert result.entry_count == 2
    assert result.size_bytes > 0
    assert result.path.exists()


@pytest.mark.unit
def test_export_csv_has_bom():
    """export_csv commence par le BOM UTF-8."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_csv(1, [entry], country="TN")
    raw = result.path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"


@pytest.mark.unit
def test_export_csv_has_headers():
    """export_csv contient les en-têtes corrects."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_csv(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    lines = raw.strip().split("\n")
    header = lines[0].replace("\ufeff", "")  # Retirer le BOM
    assert "EntryID" in header
    assert "Debit" in header
    assert "Credit" in header


@pytest.mark.unit
def test_export_csv_total_row():
    """export_csv contient une ligne de totaux."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_csv(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    assert "TOTAL" in raw


@pytest.mark.unit
def test_export_csv_custom_delimiter():
    """export_csv accepte un délimiteur personnalisé."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_csv(1, [entry], country="TN", delimiter=";")
    # Le délimiteur ; doit apparaître dans les données
    assert result.metadata["delimiter"] == ";"


# ─── Export XML ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_xml_basic(paired_entries):
    """export_xml génère un fichier XML valide."""
    result = export_xml(1, paired_entries, country="TN")
    assert result.format_name == "XML"
    assert result.entry_count == 2
    assert result.size_bytes > 0
    assert result.path.exists()


@pytest.mark.unit
def test_export_xml_has_declaration():
    """export_xml contient la déclaration XML."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_xml(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    assert raw.startswith("<?xml")


@pytest.mark.unit
def test_export_xml_has_namespace():
    """export_xml contient le namespace."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_xml(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    assert "autocommerce.example/edi/1.0" in raw


@pytest.mark.unit
def test_export_xml_has_totals():
    """export_xml contient les totaux."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_xml(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    assert "TotalDebit" in raw
    assert "TotalCredit" in raw
    assert "TotalTax" in raw


# ─── Export JSON ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_json_basic(paired_entries):
    """export_json génère un fichier JSON valide."""
    result = export_json(1, paired_entries, country="TN")
    assert result.format_name == "JSON"
    assert result.entry_count == 2
    assert result.size_bytes > 0
    assert result.path.exists()


@pytest.mark.unit
def test_export_json_valid():
    """export_json génère du JSON valide et désérialisable."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_json(1, [entry], country="TN")
    raw = json.loads(result.path.read_bytes().decode(FEC_ENCODING))
    assert raw["version"] == "1.0"
    assert raw["store_id"] == 1
    assert raw["entry_count"] == 1
    assert "totals" in raw
    assert "validation" in raw
    assert "entries" in raw


@pytest.mark.unit
def test_export_json_not_pretty():
    """export_json compact quand pretty=False."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
    )
    result = export_json(1, [entry], country="TN", pretty=False)
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    parsed = json.loads(raw)
    assert parsed["version"] == "1.0"


# ─── Export Tunisie ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_tunisia_basic(valid_entry):
    """export_tunisia génère un export conforme CGI art. 18."""
    result = export_tunisia(1, [valid_entry])
    assert result.format_name == "TUNISIA"
    assert result.country_compliance == "TN_CGI_ART18"
    assert result.size_bytes > 0


@pytest.mark.unit
def test_export_tunisia_compliance_fields():
    """export_tunisia inclut les champs de conformité CGI."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="TN123",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
        is_signed=True, signature_hash="abc",
    )
    result = export_tunisia(1, [entry])
    raw = json.loads(result.path.read_bytes().decode(FEC_ENCODING))
    assert raw["standard"] == "CGI_TUNISIE_ART18"
    assert raw["compliance"]["digital_signature_required"] is True
    assert raw["compliance"]["footer_text"] == "Conforme art. 18 CGI tunisien"
    assert "tax_rates" in raw


@pytest.mark.unit
def test_export_tunisia_unsigned_warning(valid_entry):
    """export_tunisia génère un warning pour une entrée non signée."""
    unsigned = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
        is_signed=False, signature_hash="",
    )
    result = export_tunisia(1, [unsigned])
    assert any("non signée" in w for w in result.validation_warnings)


# ─── Export Maroc ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_morocco_basic():
    """export_morocco génère un export conforme CGI marocain."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="MA123456789012345678",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.20"), tax_amount=Decimal("200"),
        currency="MAD", description="Test", store_id=1, country_code="MA",
        is_signed=True, signature_hash="abc",
    )
    result = export_morocco(1, [entry])
    assert result.format_name == "MOROCCO"
    assert result.country_compliance == "MA_CGI"
    assert result.size_bytes > 0


@pytest.mark.unit
def test_export_morocco_compliance_fields():
    """export_morocco inclut les champs ICE."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="MA123",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.20"), tax_amount=Decimal("200"),
        currency="MAD", description="Test", store_id=1, country_code="MA",
        is_signed=True, signature_hash="abc",
    )
    result = export_morocco(1, [entry])
    raw = json.loads(result.path.read_bytes().decode(FEC_ENCODING))
    assert raw["standard"] == "CGI_MAROC"
    assert "ice_format" in raw["compliance"]


@pytest.mark.unit
def test_determine_tax_regime_ma():
    """_determine_tax_regime_ma retourne le bon régime."""
    assert _determine_tax_regime_ma(Decimal("0.20")) == "normal"
    assert _determine_tax_regime_ma(Decimal("0.14")) == "intermediaire"
    assert _determine_tax_regime_ma(Decimal("0.10")) == "reduit"
    assert _determine_tax_regime_ma(Decimal("0.00")) == "exonere"


# ─── Export Algérie ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_algeria_basic():
    """export_algeria génère un export conforme CTCA algérien."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="DZ123",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="DZD", description="Test", store_id=1, country_code="DZ",
        is_signed=True, signature_hash="abc",
    )
    result = export_algeria(1, [entry])
    assert result.format_name == "ALGERIA"
    assert result.country_compliance == "DZ_CTCA"
    assert result.size_bytes > 0


@pytest.mark.unit
def test_export_algeria_compliance_fields():
    """export_algeria inclut les champs G50 et CTCA."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="DZ123",
        debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="DZD", description="Test", store_id=1, country_code="DZ",
        is_signed=True, signature_hash="abc",
    )
    result = export_algeria(1, [entry])
    raw = json.loads(result.path.read_bytes().decode(FEC_ENCODING))
    assert raw["standard"] == "CTCA_ALGERIE"
    assert raw["compliance"]["g50_form_ready"] is True
    assert raw["compliance"]["rc_required"] is True


@pytest.mark.unit
def test_determine_tax_regime_dz():
    """_determine_tax_regime_dz retourne le bon régime."""
    assert _determine_tax_regime_dz(Decimal("0.19")) == "normal"
    assert _determine_tax_regime_dz(Decimal("0.09")) == "reduit"
    assert _determine_tax_regime_dz(Decimal("0.07")) == "intermediaire"
    assert _determine_tax_regime_dz(Decimal("0.00")) == "exonere"


# ─── API compatible export_edi ───────────────────────────────────────────────


@pytest.mark.unit
def test_export_edi_compatible():
    """export_edi retourne le même format que l'API existante."""
    result = export_edi(42)
    assert isinstance(result, dict)
    assert result["status"] == "exported"
    assert result["invoice_id"] == 42
    assert "export_path" in result


@pytest.mark.unit
def test_export_edi_different_ids():
    """export_edi retourne des résultats différents pour des IDs différents."""
    r1 = export_edi(1)
    r2 = export_edi(2)
    assert r1["invoice_id"] == 1
    assert r2["invoice_id"] == 2


# ─── Exceptions métier ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_edi_export_error():
    """EDIExportError est une sous-classe de Exception."""
    exc = EDIExportError("test error")
    assert isinstance(exc, Exception)
    assert str(exc) == "test error"


@pytest.mark.unit
def test_validation_error_hierarchy():
    """ValidationError est une sous-classe de EDIExportError."""
    assert issubclass(ValidationError, EDIExportError)
    assert issubclass(AmountValidationError, ValidationError)
    assert issubclass(VATValidationError, ValidationError)
    assert issubclass(WritingVerificationError, ValidationError)


@pytest.mark.unit
def test_export_format_error():
    """ExportFormatError est une sous-classe de EDIExportError."""
    assert issubclass(ExportFormatError, EDIExportError)


@pytest.mark.unit
def test_encoding_error():
    """EncodingError est une sous-classe de EDIExportError."""
    assert issubclass(EncodingError, EDIExportError)


@pytest.mark.unit
def test_volume_exceeded_error():
    """VolumeExceededError est une sous-classe de EDIExportError."""
    assert issubclass(VolumeExceededError, EDIExportError)


@pytest.mark.unit
def test_edi_export_error_cause():
    """EDIExportError stocke la cause."""
    cause = ValueError("inner")
    exc = EDIExportError("outer", cause=cause)
    assert exc.cause is cause


@pytest.mark.unit
def test_all_exceptions_instantiable():
    """Toutes les exceptions peuvent être instanciées."""
    exceptions = [
        EDIExportError,
        ValidationError,
        AmountValidationError,
        VATValidationError,
        WritingVerificationError,
        ExportFormatError,
        EncodingError,
        VolumeExceededError,
    ]
    for exc_class in exceptions:
        exc = exc_class("test")
        assert isinstance(exc, Exception)


# ─── Dataclass tests ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_accounting_entry_as_dict():
    """AccountingEntry.as_dict() retourne un dictionnaire complet."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Client", partner_vat="TN123",
        debit=Decimal("1000"), credit=Decimal("0"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Test", store_id=1, country_code="TN",
        is_signed=True, signature_hash="abc",
    )
    d = entry.as_dict()
    assert d["entry_id"] == "E1"
    assert d["currency"] == "TND"
    assert isinstance(d["debit"], str)  # Decimal sérialisé en string


@pytest.mark.unit
def test_export_result_as_dict():
    """ExportResult.as_dict() retourne un dictionnaire sérialisable."""
    result = ExportResult(
        format_name="JSON", filename="test.json", path=Path("/tmp/test.json"),
        size_bytes=100, entry_count=5, created_at="2026-01-01",
        checksum="abc123", country_compliance="TN_JSON",
    )
    d = result.as_dict()
    assert d["format"] == "JSON"
    assert d["filename"] == "test.json"
    assert isinstance(d["path"], str)


@pytest.mark.unit
def test_validation_result_as_dict():
    """ValidationResult.as_dict() retourne un dictionnaire sérialisable."""
    result = ValidationResult(
        is_valid=True, errors=[], warnings=["w1"],
        entry_count=10, total_debit=Decimal("1000"),
        total_credit=Decimal("1000"), total_tax=Decimal("190"),
    )
    d = result.as_dict()
    assert d["is_valid"] is True
    assert isinstance(d["total_debit"], str)


# ─── Constantes ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fec_version():
    """FEC_VERSION est une chaîne valide."""
    assert isinstance(FEC_VERSION, str)
    assert FEC_VERSION == "1.0"


@pytest.mark.unit
def test_fec_encoding():
    """FEC_ENCODING est UTF-8."""
    assert FEC_ENCODING == "utf-8"


@pytest.mark.unit
def test_fec_bom():
    """FEC_BOM est le BOM UTF-8 correct."""
    assert FEC_BOM == b"\xef\xbb\xbf"


@pytest.mark.unit
def test_chunk_size():
    """CHUNK_SIZE est un entier positif."""
    assert isinstance(CHUNK_SIZE, int)
    assert CHUNK_SIZE > 0


@pytest.mark.unit
def test_tva_rates_tn():
    """TVA_RATES_TN contient les 4 taux tunisiens."""
    assert "normal" in TVA_RATES_TN
    assert "intermediate" in TVA_RATES_TN
    assert "reduced" in TVA_RATES_TN
    assert "exempt" in TVA_RATES_TN
    assert TVA_RATES_TN["normal"] == Decimal("0.19")
    assert TVA_RATES_TN["exempt"] == Decimal("0.00")


@pytest.mark.unit
def test_tva_rates_ma():
    """TVA_RATES_MA contient les 4 taux marocains."""
    assert "normal" in TVA_RATES_MA
    assert "intermediate" in TVA_RATES_MA
    assert "reduced" in TVA_RATES_MA
    assert "exempt" in TVA_RATES_MA


@pytest.mark.unit
def test_tva_rates_dz():
    """TVA_RATES_DZ contient les 4 taux algériens."""
    assert "normal" in TVA_RATES_DZ
    assert "reduced" in TVA_RATES_DZ
    assert "intermediate" in TVA_RATES_DZ
    assert "exempt" in TVA_RATES_DZ


@pytest.mark.unit
def test_tva_rates_fr():
    """TVA_RATES_FR contient les 5 taux français."""
    assert "normal" in TVA_RATES_FR
    assert "intermediate" in TVA_RATES_FR
    assert "reduced" in TVA_RATES_FR
    assert "super_reduced" in TVA_RATES_FR
    assert "exempt" in TVA_RATES_FR


# ─── Gestion UTF-8 ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_csv_utf8_accents():
    """export_csv gère correctement les accents UTF-8."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Café René & Frères",
        partner_vat="", debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Pièces d'échappement pour véhicules à moteur",
        store_id=1, country_code="TN",
    )
    result = export_csv(1, [entry], country="TN")
    raw = result.path.read_bytes().decode(FEC_ENCODING)
    assert "Café" in raw


@pytest.mark.unit
def test_export_json_utf8():
    """export_json gère correctement les caractères UTF-8."""
    entry = AccountingEntry(
        entry_id="E1", journal_code="VT", journal_label="Ventes",
        document_number="INV-001", document_date="2026-01-01T00:00:00+00:00",
        document_type="invoice", account_number="707100", account_label="Ventes",
        partner_code="CLI", partner_label="Café René",
        partner_vat="", debit=Decimal("0"), credit=Decimal("1000"),
        tax_rate=Decimal("0.19"), tax_amount=Decimal("190"),
        currency="TND", description="Pièces d'échappement",
        store_id=1, country_code="TN",
    )
    result = export_json(1, [entry], country="TN")
    raw = json.loads(result.path.read_bytes().decode(FEC_ENCODING))
    assert "Café" in raw["entries"][0]["partner_label"]


# ─── Gros volumes ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_json_large_volume():
    """export_json gère un grand volume d'entrées."""
    entries = [
        AccountingEntry(
            entry_id=f"E{i}", journal_code="VT", journal_label="Ventes",
            document_number=f"INV-{i:06d}", document_date="2026-01-01T00:00:00+00:00",
            document_type="invoice", account_number="707100", account_label="Ventes",
            partner_code="CLI", partner_label="Client", partner_vat="",
            debit=Decimal("100"), credit=Decimal("0"),
            tax_rate=Decimal("0.19"), tax_amount=Decimal("19"),
            currency="TND", description="Test", store_id=1, country_code="TN",
        )
        for i in range(2500)
    ]
    result = export_json(1, entries, country="TN")
    assert result.entry_count == 2500
    assert result.size_bytes > 0


@pytest.mark.unit
def test_export_csv_large_volume():
    """export_csv gère un grand volume d'entrées via chunks."""
    entries = [
        AccountingEntry(
            entry_id=f"E{i}", journal_code="VT", journal_label="Ventes",
            document_number=f"INV-{i:06d}", document_date="2026-01-01T00:00:00+00:00",
            document_type="invoice", account_number="707100", account_label="Ventes",
            partner_code="CLI", partner_label="Client", partner_vat="",
            debit=Decimal("100"), credit=Decimal("0"),
            tax_rate=Decimal("0.19"), tax_amount=Decimal("19"),
            currency="TND", description="Test", store_id=1, country_code="TN",
        )
        for i in range(2500)
    ]
    result = export_csv(1, entries, country="TN")
    assert result.entry_count == 2500
    assert result.size_bytes > 0


# ─── As_dict tests ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_export_result_as_dict_complete():
    """ExportResult.as_dict() retourne tous les champs."""
    result = ExportResult(
        format_name="JSON", filename="test.json", path=Path("/tmp/test.json"),
        size_bytes=100, entry_count=5, created_at="2026-01-01",
        checksum="abc123", country_compliance="TN_JSON",
        validation_warnings=["w1"], metadata={"key": "val"},
    )
    d = result.as_dict()
    assert d["validation_warnings"] == ["w1"]
    assert d["metadata"] == {"key": "val"}
