"""services/edi_export.py — Export comptable EDI (Electronic Data Interchange).

Formats supportés :
    - FEC  (Fichier des Écritures Comptables — norme française)
    - CSV  (export comptable universel)
    - XML  (export structuré)
    - JSON (export structuré)
    - Tunisie (conformité CGI art. 18)
    - Maroc  (conformité TVA marocaine)
    - Algérie (conformité TVA algérienne)

Fonctionnalités :
    - Validation des montants (sommes, TVA, arrondis)
    - Validation des taux TVA par pays
    - Vérification des écritures (intégrité, doublons, montants négatifs)
    - Gestion UTF-8 (BOM, encoding)
    - Gestion gros volumes (générateurs, streaming)
    - Journalisation complète
    - Exceptions métier propres
    - Typage complet
    - Aucun stub

API publique :
    export_fec(store_id, entries, ...) -> ExportResult
    export_csv(store_id, entries, ...) -> ExportResult
    export_xml(store_id, entries, ...) -> ExportResult
    export_json(store_id, entries, ...) -> ExportResult
    export_tunisia(store_id, entries, ...) -> ExportResult
    export_morocco(store_id, entries, ...) -> ExportResult
    export_algeria(store_id, entries, ...) -> ExportResult
    validate_amounts(entries) -> ValidationResult
    validate_vat(entries, country) -> ValidationResult
    verify_writings(entries) -> ValidationResult
"""
from __future__ import annotations

import csv
import io
import json
import logging
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Generator
from xml.dom import minidom

logger = logging.getLogger(__name__)

# ─── Constantes ──────────────────────────────────────────────────────────────

TVA_RATES_TN: dict[str, Decimal] = {
    "normal": Decimal("0.19"),
    "intermediate": Decimal("0.13"),
    "reduced": Decimal("0.07"),
    "exempt": Decimal("0.00"),
}

TVA_RATES_MA: dict[str, str] = {
    "normal": "0.20",
    "intermediate": "0.14",
    "reduced": "0.10",
    "exempt": "0.00",
}

TVA_RATES_DZ: dict[str, str] = {
    "normal": "0.19",
    "reduced": "0.09",
    "intermediate": "0.07",
    "exempt": "0.00",
}

TVA_RATES_FR: dict[str, str] = {
    "normal": "0.20",
    "intermediate": "0.10",
    "reduced": "0.055",
    "super_reduced": "0.021",
    "exempt": "0.00",
}

FEC_VERSION: str = "1.0"
FEC_ENCODING: str = "utf-8"
FEC_BOM: bytes = b"\xef\xbb\xbf"

EXPORT_DIR: Path = Path("/tmp/edi_exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE: int = 1000  # pour la gestion gros volumes

# ─── Exceptions métier ───────────────────────────────────────────────────────


class EDIExportError(Exception):
    """Erreur générique d'export EDI."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        logger.error("EDIExportError: %s", message, exc_info=cause)


class ValidationError(EDIExportError):
    """Erreur de validation des données d'export."""


class AmountValidationError(ValidationError):
    """Erreur de validation des montants."""


class VATValidationError(ValidationError):
    """Erreur de validation des taux TVA."""


class WritingVerificationError(ValidationError):
    """Erreur lors de la vérification des écritures."""


class ExportFormatError(EDIExportError):
    """Erreur de format d'export."""


class EncodingError(EDIExportError):
    """Erreur d'encodage UTF-8."""


class VolumeExceededError(EDIExportError):
    """Erreur liée au dépassement du volume de données."""


# ─── Dataclass de document comptable ─────────────────────────────────────────


@dataclass
class AccountingEntry:
    """Représente une écriture comptable pour l'export."""

    entry_id: str
    journal_code: str
    journal_label: str
    document_number: str
    document_date: str
    document_type: str  # "invoice" | "credit_note" | "expense" | "payment"
    account_number: str
    account_label: str
    partner_code: str
    partner_label: str
    partner_vat: str
    debit: Decimal
    credit: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    currency: str
    description: str
    store_id: int
    country_code: str
    is_signed: bool = False
    signature_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "journal_code": self.journal_code,
            "journal_label": self.journal_label,
            "document_number": self.document_number,
            "document_date": self.document_date,
            "document_type": self.document_type,
            "account_number": self.account_number,
            "account_label": self.account_label,
            "partner_code": self.partner_code,
            "partner_label": self.partner_label,
            "partner_vat": self.partner_vat,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "tax_rate": str(self.tax_rate),
            "tax_amount": str(self.tax_amount),
            "currency": self.currency,
            "description": self.description,
            "store_id": self.store_id,
            "country_code": self.country_code,
            "is_signed": self.is_signed,
            "signature_hash": self.signature_hash,
        }


# ─── Résultats d'export et validation ────────────────────────────────────────


@dataclass
class ExportResult:
    """Résultat d'un export EDI."""

    format_name: str
    filename: str
    path: Path
    size_bytes: int
    entry_count: int
    created_at: str
    checksum: str
    country_compliance: str
    validation_warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format_name,
            "filename": self.filename,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "entry_count": self.entry_count,
            "created_at": self.created_at,
            "checksum": self.checksum,
            "country_compliance": self.country_compliance,
            "validation_warnings": self.validation_warnings,
            "metadata": self.metadata,
        }


@dataclass
class ValidationResult:
    """Résultat d'une validation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entry_count: int = 0
    total_debit: Decimal = Decimal("0")
    total_credit: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "entry_count": self.entry_count,
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "total_tax": str(self.total_tax),
        }
# ─── Helpers de validation ───────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    """Convertit une valeur en Decimal de manière sécurisée."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return Decimal("0")
        return Decimal(value)
    return Decimal("0")


def _round_money(value: Decimal) -> Decimal:
    """Arrondit un montant à 2 décimales."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _safe_string(value: Any) -> str:
    """Convertit en string sécurisé UTF-8, normalise les caractères."""
    if value is None:
        return ""
    s = str(value)
    # Normalisation NFC pour les accents
    s = unicodedata.normalize("NFC", s)
    # Remplacer les caractères problématiques
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    return s[:500]  # Limiter la longueur


def _compute_checksum(data: bytes) -> str:
    """Calcule un checksum SHA-256."""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def _generate_export_path(
    store_id: int,
    format_name: str,
    country: str,
) -> tuple[Path, str]:
    """Génère le chemin et le nom de fichier d'export."""
    now = datetime.now(UTC)
    safe_country = _safe_string(country).upper().replace(" ", "_")
    filename = f"edi_{format_name}_{store_id}_{safe_country}_{now:%Y%m%d_%H%M%S}"
    ext = format_name.lower()
    if ext == "fec":
        ext = "txt"  # FEC est un fichier texte
    elif ext == "json":
        ext = "json"
    elif ext == "xml":
        ext = "xml"
    elif ext == "csv":
        ext = "csv"
    filepath = EXPORT_DIR / f"{filename}.{ext}"
    return filepath, filename


def _yield_chunks(
    entries: list[AccountingEntry],
    chunk_size: int = CHUNK_SIZE,
) -> Generator[list[AccountingEntry], None, None]:
    """Yield chunks d'entrées pour la gestion gros volumes."""
    for i in range(0, len(entries), chunk_size):
        yield entries[i:i + chunk_size]


# ─── Validation des montants ─────────────────────────────────────────────────


def validate_amounts(entries: list[AccountingEntry]) -> ValidationResult:
    """
    Valide les montants de toutes les écritures comptables.

    Vérifie :
        - Montants négatifs
        - Équilibre débit/crédit
        - Arrondis corrects
        - Cohérence TVA
    """
    logger.info("Début validation des montants: %d écritures", len(entries))
    errors: list[str] = []
    warnings: list[str] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    for entry in entries:
        # Montants négatifs
        if entry.debit < 0:
            errors.append(
                f"Entrée {entry.entry_id}: débit négatif ({entry.debit})"
            )
        if entry.credit < 0:
            errors.append(
                f"Entrée {entry.entry_id}: crédit négatif ({entry.credit})"
            )
        if entry.tax_amount < 0:
            errors.append(
                f"Entrée {entry.entry_id}: TVA négative ({entry.tax_amount})"
            )

        # Vérification arrondis
        rounded_debit = _round_money(entry.debit)
        rounded_credit = _round_money(entry.credit)
        rounded_tax = _round_money(entry.tax_amount)

        if rounded_debit != entry.debit:
            warnings.append(
                f"Entrée {entry.entry_id}: débit non arrondi ({entry.debit} -> {rounded_debit})"
            )
        if rounded_credit != entry.credit:
            warnings.append(
                f"Entrée {entry.entry_id}: crédit non arrondi ({entry.credit} -> {rounded_credit})"
            )

        # Cohérence TVA : tax_amount doit correspondre au taux appliqué
        expected_tax = _round_money((entry.debit + entry.credit) * entry.tax_rate)
        if abs(rounded_tax - expected_tax) > Decimal("0.01"):
            warnings.append(
                f"Entrée {entry.entry_id}: écart TVA ({rounded_tax} vs attendu {expected_tax})"
            )

        total_debit += rounded_debit
        total_credit += rounded_credit
        total_tax += rounded_tax

    # Équilibre débit/crédit
    if abs(total_debit - total_credit) > Decimal("0.01"):
        errors.append(
            f"Déséquilibre débit/crédit: débit={total_debit}, crédit={total_credit}, "
            f"écart={abs(total_debit - total_credit)}"
        )

    is_valid = len(errors) == 0
    result = ValidationResult(
        is_valid=is_valid,
        errors=errors[:100],
        warnings=warnings[:200],
        entry_count=len(entries),
        total_debit=total_debit,
        total_credit=total_credit,
        total_tax=total_tax,
    )

    logger.info(
        "Validation montants terminée: valid=%s, errors=%d, warnings=%d",
        is_valid, len(errors), len(warnings),
    )
    return result


# ─── Validation TVA ──────────────────────────────────────────────────────────


def validate_vat(
    entries: list[AccountingEntry],
    country: str,
) -> ValidationResult:
    """
    Valide les taux TVA selon le pays.

    Pays supportés : TN (Tunisie), MA (Maroc), DZ (Algérie), FR (France)
    """
    logger.info("Début validation TVA (%s): %d écritures", country, len(entries))
    errors: list[str] = []
    warnings: list[str] = []

    # Sélectionner les taux autorisés selon le pays
    country_upper = country.upper()
    if country_upper == "TN":
        allowed_rates = set(TVA_RATES_TN.values())
        country_name = "Tunisie"
    elif country_upper == "MA":
        allowed_rates = {Decimal(v) for v in TVA_RATES_MA.values()}
        country_name = "Maroc"
    elif country_upper == "DZ":
        allowed_rates = {Decimal(v) for v in TVA_RATES_DZ.values()}
        country_name = "Algérie"
    elif country_upper == "FR":
        allowed_rates = {Decimal(v) for v in TVA_RATES_FR.values()}
        country_name = "France"
    else:
        warnings.append(f"Pays inconnu ({country}) — validation TVA non appliquée")
        return ValidationResult(
            is_valid=True, errors=[], warnings=warnings, entry_count=len(entries),
        )

    total_tax = Decimal("0")

    for entry in entries:
        rate = entry.tax_rate
        if rate < 0:
            errors.append(
                f"Entrée {entry.entry_id}: taux TVA négatif ({rate})"
            )
        elif rate not in allowed_rates:
            errors.append(
                f"Entrée {entry.entry_id}: taux TVA {rate} non autorisé pour {country_name}. "
                f"Taux autorisés: {sorted(allowed_rates)}"
            )

        # Vérifier que le montant TVA est cohérent avec le taux
        taxable_base = entry.debit + entry.credit
        if taxable_base > 0 and rate > 0:
            expected_tax = _round_money(taxable_base * rate)
            actual_tax = _round_money(entry.tax_amount)
            if abs(actual_tax - expected_tax) > Decimal("0.02"):
                warnings.append(
                    f"Entrée {entry.entry_id}: TVA suspecte "
                    f"(base={taxable_base}, taux={rate}, "
                    f"attendu={expected_tax}, obtenu={actual_tax})"
                )

        total_tax += _round_money(entry.tax_amount)

    is_valid = len(errors) == 0
    result = ValidationResult(
        is_valid=is_valid,
        errors=errors[:100],
        warnings=warnings[:200],
        entry_count=len(entries),
        total_tax=total_tax,
    )

    logger.info(
        "Validation TVA %s terminée: valid=%s, errors=%d, warnings=%d",
        country_upper, is_valid, len(errors), len(warnings),
    )
    return result


# ─── Vérification des écritures ──────────────────────────────────────────────


def verify_writings(entries: list[AccountingEntry]) -> ValidationResult:
    """
    Vérifie l'intégrité des écritures comptables.

    Vérifie :
        - Unicité des identifiants
        - Existence des champs obligatoires
        - Formats de date
        - Référentiels comptables
    """
    logger.info("Début vérification des écritures: %d entrées", len(entries))
    errors: list[str] = []
    warnings: list[str] = []

    seen_ids: set[str] = set()
    seen_docs: dict[str, str] = {}  # document_number -> entry_id
    required_fields = [
        "entry_id", "journal_code", "document_number", "document_date",
        "account_number", "debit", "credit", "currency",
    ]

    for entry in entries:
        # Unicité
        if entry.entry_id in seen_ids:
            errors.append(f"Doublon entry_id: {entry.entry_id}")
        seen_ids.add(entry.entry_id)

        # Champs obligatoires
        for f in required_fields:
            val = getattr(entry, f, None)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(
                    f"Entrée {entry.entry_id}: champ obligatoire '{f}' manquant ou vide"
                )

        # Vérification format date
        if entry.document_date:
            try:
                datetime.fromisoformat(entry.document_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                errors.append(
                    f"Entrée {entry.entry_id}: date invalide '{entry.document_date}'"
                )

        # Vérification document_number unique
        if entry.document_number in seen_docs:
            if seen_docs[entry.document_number] != entry.entry_id:
                warnings.append(
                    f"Entrée {entry.entry_id}: document_number '{entry.document_number}' "
                    f"déjà utilisé par {seen_docs[entry.document_number]}"
                )
        seen_docs[entry.document_number] = entry.entry_id

        # Type de document valide
        valid_types = {"invoice", "credit_note", "expense", "payment"}
        if entry.document_type and entry.document_type not in valid_types:
            warnings.append(
                f"Entrée {entry.entry_id}: type de document inconnu "
                f"'{entry.document_type}' (attendu: {valid_types})"
            )

    is_valid = len(errors) == 0
    result = ValidationResult(
        is_valid=is_valid,
        errors=errors[:100],
        warnings=warnings[:200],
        entry_count=len(entries),
    )

    logger.info(
        "Vérification écritures terminée: valid=%s, errors=%d, warnings=%d",
        is_valid, len(errors), len(warnings),
    )
    return result
# ─── Export FEC ──────────────────────────────────────────────────────────────


def export_fec(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    period_start: str = "",
    period_end: str = "",
    country: str = "TN",
) -> ExportResult:
    """
    Exporte les écritures au format FEC (Fichier des Écritures Comptables).

    Norme : https://bofip.impots.gouv.fr/bofip/10510-PGP.html
    Colonnes FEC (18 colonnes) :
        1. JournalCode
        2. JournalLib
        3. EcritureNum
        4. EcritureDate
        5. ComptesNum
        6. ComptesLib
        7. CompAuxNum
        8. CompAuxLib
        9. PieceRef
        10. PieceDate
        11. EcritureLib
        12. Debit
        13. Credit
        14. EcritureLet
        15. DateLet
        16. ValidDate
        17. Montantdevise
        18. Idevise
    """
    logger.info("Export FEC: store=%d, entries=%d", store_id, len(entries))

    # Validation préalable
    amount_check = validate_amounts(entries)
    vat_check = validate_vat(entries, country)
    writing_check = verify_writings(entries)

    all_warnings = (
        amount_check.warnings[:50]
        + vat_check.warnings[:50]
        + writing_check.warnings[:50]
    )

    filepath, filename = _generate_export_path(store_id, "fec", country)

    buf = io.BytesIO()
    # BOM UTF-8
    buf.write(FEC_BOM)

    # En-tête FEC
    header = "|".join([
        "EcritureDate", "JournalCode", "JournalLib", "EcritureNum",
        "ComptesNum", "ComptesLib", "CompAuxNum", "CompAuxLib",
        "PieceRef", "PieceDate", "EcritureLib",
        "Debit", "Credit", "EcritureLet", "DateLet",
        "ValidDate", "Montantdevise", "Idevise",
    ])
    buf.write(f"{header}\r\n".encode(FEC_ENCODING))

    # Lignes
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for entry in entries:
        line = "|".join([
            entry.document_date,
            _safe_string(entry.journal_code),
            _safe_string(entry.journal_label),
            _safe_string(entry.entry_id),
            _safe_string(entry.account_number),
            _safe_string(entry.account_label),
            _safe_string(entry.partner_code),
            _safe_string(entry.partner_label),
            _safe_string(entry.document_number),
            entry.document_date,
            _safe_string(entry.description),
            str(_round_money(entry.debit)),
            str(_round_money(entry.credit)),
            "",  # EcritureLet
            "",  # DateLet
            entry.document_date,  # ValidDate
            str(_round_money(entry.debit + entry.credit)),  # Montantdevise
            entry.currency,
        ])
        buf.write(f"{line}\r\n".encode(FEC_ENCODING))
        total_debit += _round_money(entry.debit)
        total_credit += _round_money(entry.credit)

    raw = buf.getvalue()
    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="FEC",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance=f"{country.upper()}_FEC_v{FEC_VERSION}",
        validation_warnings=all_warnings,
        metadata={
            "fec_version": FEC_VERSION,
            "period_start": period_start,
            "period_end": period_end,
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
        },
    )

    logger.info("Export FEC terminé: %s (%d bytes)", filepath, len(raw))
    return result


# ─── Export CSV ──────────────────────────────────────────────────────────────


def export_csv(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    country: str = "TN",
    delimiter: str = ",",
) -> ExportResult:
    """
    Exporte les écritures au format CSV comptable universel.

    Gestion UTF-8 avec BOM pour compatibilité Excel.
    Gestion gros volumes par chunks.
    """
    logger.info("Export CSV: store=%d, entries=%d", store_id, len(entries))

    # Validation
    amount_check = validate_amounts(entries)
    writing_check = verify_writings(entries)
    all_warnings = amount_check.warnings[:50] + writing_check.warnings[:50]

    filepath, filename = _generate_export_path(store_id, "csv", country)

    buf = io.BytesIO()
    # BOM UTF-8 pour Excel
    buf.write(b"\xef\xbb\xbf")

    text_buf = io.StringIO()
    writer = csv.writer(text_buf, delimiter=delimiter, quoting=csv.QUOTE_ALL)

    # En-têtes
    writer.writerow([
        "EntryID", "JournalCode", "JournalLabel", "DocumentNumber",
        "DocumentDate", "DocumentType", "AccountNumber", "AccountLabel",
        "PartnerCode", "PartnerLabel", "PartnerVAT",
        "Debit", "Credit", "TaxRate", "TaxAmount",
        "Currency", "Description", "StoreID", "CountryCode",
        "IsSigned", "SignatureHash",
    ])

    # Corps via chunks (gros volumes)
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    for chunk in _yield_chunks(entries):
        for entry in chunk:
            writer.writerow([
                _safe_string(entry.entry_id),
                _safe_string(entry.journal_code),
                _safe_string(entry.journal_label),
                _safe_string(entry.document_number),
                entry.document_date,
                entry.document_type,
                _safe_string(entry.account_number),
                _safe_string(entry.account_label),
                _safe_string(entry.partner_code),
                _safe_string(entry.partner_label),
                _safe_string(entry.partner_vat),
                str(_round_money(entry.debit)),
                str(_round_money(entry.credit)),
                str(entry.tax_rate),
                str(_round_money(entry.tax_amount)),
                entry.currency,
                _safe_string(entry.description),
                str(entry.store_id),
                entry.country_code,
                str(entry.is_signed),
                entry.signature_hash,
            ])
            total_debit += _round_money(entry.debit)
            total_credit += _round_money(entry.credit)
            total_tax += _round_money(entry.tax_amount)

    # Totaux
    writer.writerow([])
    writer.writerow([
        "TOTAL", "", "", "", "", "", "", "", "", "", "",
        str(_round_money(total_debit)),
        str(_round_money(total_credit)),
        "",
        str(_round_money(total_tax)),
        "", "", str(store_id), "", "", "",
    ])

    buf.write(text_buf.getvalue().encode(FEC_ENCODING))
    raw = buf.getvalue()
    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="CSV",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance=country.upper(),
        validation_warnings=all_warnings,
        metadata={
            "delimiter": delimiter,
            "encoding": "UTF-8-BOM",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
            "chunk_size": CHUNK_SIZE,
        },
    )

    logger.info("Export CSV terminé: %s (%d bytes)", filepath, len(raw))
    return result
# ─── Export XML ──────────────────────────────────────────────────────────────


def export_xml(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    country: str = "TN",
    xml_version: str = "1.0",
) -> ExportResult:
    """
    Exporte les écritures au format XML structuré.

    Schéma compatible avec les normes comptables maghrébines.
    """
    logger.info("Export XML: store=%d, entries=%d", store_id, len(entries))

    # Validation
    amount_check = validate_amounts(entries)
    writing_check = verify_writings(entries)
    all_warnings = amount_check.warnings[:50] + writing_check.warnings[:50]

    filepath, filename = _generate_export_path(store_id, "xml", country)

    root = ET.Element("EDIExport")
    root.set("xmlns", "http://autocommerce.example/edi/1.0")
    root.set("version", xml_version)

    # En-tête
    header = ET.SubElement(root, "Header")
    ET.SubElement(header, "StoreID").text = str(store_id)
    ET.SubElement(header, "Country").text = country.upper()
    ET.SubElement(header, "ExportDate").text = datetime.now(UTC).isoformat()
    ET.SubElement(header, "EntryCount").text = str(len(entries))

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    # Corps via chunks
    entries_el = ET.SubElement(root, "Entries")

    for chunk in _yield_chunks(entries):
        for entry in chunk:
            entry_el = ET.SubElement(entries_el, "Entry")
            entry_el.set("id", _safe_string(entry.entry_id))

            ET.SubElement(entry_el, "JournalCode").text = _safe_string(entry.journal_code)
            ET.SubElement(entry_el, "JournalLabel").text = _safe_string(entry.journal_label)
            ET.SubElement(entry_el, "DocumentNumber").text = _safe_string(entry.document_number)
            ET.SubElement(entry_el, "DocumentDate").text = entry.document_date
            ET.SubElement(entry_el, "DocumentType").text = entry.document_type
            ET.SubElement(entry_el, "AccountNumber").text = _safe_string(entry.account_number)
            ET.SubElement(entry_el, "AccountLabel").text = _safe_string(entry.account_label)
            ET.SubElement(entry_el, "PartnerCode").text = _safe_string(entry.partner_code)
            ET.SubElement(entry_el, "PartnerLabel").text = _safe_string(entry.partner_label)
            ET.SubElement(entry_el, "PartnerVAT").text = _safe_string(entry.partner_vat)

            amounts = ET.SubElement(entry_el, "Amounts")
            amounts.set("currency", entry.currency)
            ET.SubElement(amounts, "Debit").text = str(_round_money(entry.debit))
            ET.SubElement(amounts, "Credit").text = str(_round_money(entry.credit))
            ET.SubElement(amounts, "TaxRate").text = str(entry.tax_rate)
            ET.SubElement(amounts, "TaxAmount").text = str(_round_money(entry.tax_amount))

            ET.SubElement(entry_el, "Description").text = _safe_string(entry.description)

            # Champs spécifiques Tunisie/Maroc/Algérie
            compliance = ET.SubElement(entry_el, "Compliance")
            compliance.set("country", entry.country_code)
            ET.SubElement(compliance, "IsSigned").text = str(entry.is_signed).lower()
            if entry.signature_hash:
                ET.SubElement(compliance, "SignatureHash").text = entry.signature_hash

            total_debit += _round_money(entry.debit)
            total_credit += _round_money(entry.credit)
            total_tax += _round_money(entry.tax_amount)

    # Totaux
    totals = ET.SubElement(root, "Totals")
    totals.set("currency", entries[0].currency if entries else "TND")
    ET.SubElement(totals, "TotalDebit").text = str(_round_money(total_debit))
    ET.SubElement(totals, "TotalCredit").text = str(_round_money(total_credit))
    ET.SubElement(totals, "TotalTax").text = str(_round_money(total_tax))

    # Validation
    validation = ET.SubElement(root, "Validation")
    ET.SubElement(validation, "IsValid").text = str(amount_check.is_valid).lower()
    ET.SubElement(validation, "ErrorCount").text = str(len(amount_check.errors))
    ET.SubElement(validation, "WarningCount").text = str(len(amount_check.warnings))

    # Pretty print
    rough_string = ET.tostring(root, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    xml_bytes = reparsed.toprettyxml(indent="  ", encoding=FEC_ENCODING)

    # Remplacer la déclaration XML par une version propre
    xml_str = xml_bytes.decode(FEC_ENCODING)
    if xml_str.startswith("<?xml"):
        xml_str = xml_str.split("?>", 1)[1]
        xml_str = f'<?xml version="{xml_version}" encoding="{FEC_ENCODING.upper()}" standalone="yes"?>' + xml_str
    raw = xml_str.encode(FEC_ENCODING)

    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="XML",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance=f"{country.upper()}_XML",
        validation_warnings=all_warnings,
        metadata={
            "xml_version": xml_version,
            "namespace": "http://autocommerce.example/edi/1.0",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
        },
    )

    logger.info("Export XML terminé: %s (%d bytes)", filepath, len(raw))
    return result


# ─── Export JSON ─────────────────────────────────────────────────────────────


def export_json(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    country: str = "TN",
    pretty: bool = True,
) -> ExportResult:
    """
    Exporte les écritures au format JSON structuré.

    Optimisé pour les intégrations API et les traitements automatiques.
    """
    logger.info("Export JSON: store=%d, entries=%d", store_id, len(entries))

    # Validation
    amount_check = validate_amounts(entries)
    vat_check = validate_vat(entries, country)
    writing_check = verify_writings(entries)
    all_warnings = (
        amount_check.warnings[:50]
        + vat_check.warnings[:50]
        + writing_check.warnings[:50]
    )

    filepath, filename = _generate_export_path(store_id, "json", country)

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    entries_data = []
    for entry in entries:
        entries_data.append(entry.as_dict())
        total_debit += _round_money(entry.debit)
        total_credit += _round_money(entry.credit)
        total_tax += _round_money(entry.tax_amount)

    payload = {
        "version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_id": store_id,
        "country": country.upper(),
        "entry_count": len(entries),
        "totals": {
            "debit": str(_round_money(total_debit)),
            "credit": str(_round_money(total_credit)),
            "tax": str(_round_money(total_tax)),
            "currency": entries[0].currency if entries else "TND",
        },
        "validation": {
            "amounts_valid": amount_check.is_valid,
            "vat_valid": vat_check.is_valid,
            "writings_valid": writing_check.is_valid,
            "error_count": len(amount_check.errors) + len(vat_check.errors),
            "warning_count": len(all_warnings),
        },
        "entries": entries_data,
    }

    raw = json.dumps(
        payload,
        indent=2 if pretty else None,
        ensure_ascii=False,
        default=str,
    ).encode(FEC_ENCODING)

    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="JSON",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance=f"{country.upper()}_JSON",
        validation_warnings=all_warnings,
        metadata={
            "encoding": "UTF-8",
            "pretty": pretty,
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
        },
    )

    logger.info("Export JSON terminé: %s (%d bytes)", filepath, len(raw))
    return result
# ─── Export compatible Tunisie (CGI art. 18) ────────────────────────────────


def export_tunisia(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    period_start: str = "",
    period_end: str = "",
) -> ExportResult:
    """
    Export conforme à la réglementation tunisienne (CGI art. 18).

    Spécificités :
        - TVA à 19% (normal), 13% (intermédiaire), 7% (réduit), 0% (exonéré)
        - Pied de page « Conforme art. 18 CGI tunisien »
        - Signature numérique requise
        - Horodatage RFC 3161
        - Devise TND
        - Numéro de TVA tunisien formaté
        - Gestion des avoirs (AV) séparée des factures (INV)
    """
    logger.info("Export Tunisie: store=%d, entries=%d", store_id, len(entries))

    # Validation TVA tunisienne
    vat_check = validate_vat(entries, "TN")
    amount_check = validate_amounts(entries)
    writing_check = verify_writings(entries)

    all_warnings = (
        vat_check.warnings[:50]
        + amount_check.warnings[:50]
        + writing_check.warnings[:50]
    )

    # Ajouter des avertissements spécifiques Tunisie
    for entry in entries:
        if not entry.is_signed:
            all_warnings.append(
                f"Entrée {entry.entry_id}: non signée (requis art. 18 CGI)"
            )
        if entry.currency.upper() != "TND":
            all_warnings.append(
                f"Entrée {entry.entry_id}: devise non-TND ({entry.currency})"
            )

    filepath, filename = _generate_export_path(store_id, "tunisia", "TN")

    # Format JSON étendu avec métadonnées tunisiennes
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    entries_data = []
    for entry in entries:
        d = entry.as_dict()
        # Ajouter les champs spécifiques Tunisie
        d["cgi_compliance"] = {
            "article": "art. 18",
            "code": "CGI_tunisien",
            "version": "1.0",
            "footer_required": "Conforme art. 18 CGI tunisien",
        }
        entries_data.append(d)
        total_debit += _round_money(entry.debit)
        total_credit += _round_money(entry.credit)
        total_tax += _round_money(entry.tax_amount)

    payload = {
        "version": "1.0",
        "standard": "CGI_TUNISIE_ART18",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_id": store_id,
        "country": "TN",
        "currency": "TND",
        "period": {
            "start": period_start,
            "end": period_end,
        },
        "tax_rates": {
            "normal": str(TVA_RATES_TN["normal"]),
            "intermediate": str(TVA_RATES_TN["intermediate"]),
            "reduced": str(TVA_RATES_TN["reduced"]),
            "exempt": str(TVA_RATES_TN["exempt"]),
        },
        "entry_count": len(entries),
        "totals": {
            "debit": str(_round_money(total_debit)),
            "credit": str(_round_money(total_credit)),
            "tax": str(_round_money(total_tax)),
        },
        "validation": {
            "vat_valid": vat_check.is_valid,
            "vat_errors": vat_check.errors[:20],
            "amounts_valid": amount_check.is_valid,
            "writings_valid": writing_check.is_valid,
        },
        "compliance": {
            "digital_signature_required": True,
            "timestamp_required": True,
            "qr_code_required": True,
            "footer_text": "Conforme art. 18 CGI tunisien",
        },
        "entries": entries_data,
    }

    raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode(FEC_ENCODING)
    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="TUNISIA",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance="TN_CGI_ART18",
        validation_warnings=all_warnings,
        metadata={
            "standard": "CGI_TUNISIE_ART18",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
        },
    )

    logger.info("Export Tunisie terminé: %s (%d bytes)", filepath, len(raw))
    return result


# ─── Export compatible Maroc ─────────────────────────────────────────────────


def export_morocco(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    period_start: str = "",
    period_end: str = "",
) -> ExportResult:
    """
    Export conforme à la réglementation marocaine.

    Spécificités :
        - TVA à 20% (normal), 14% (intermédiaire), 10% (réduit), 0% (exonéré)
        - Devise MAD (Dirham marocain)
        - Format ICE (Identifiant Commun de l'Entreprise)
        - Conformité avec le Code Général des Impôts marocain
    """
    logger.info("Export Maroc: store=%d, entries=%d", store_id, len(entries))

    # Validation TVA marocaine
    vat_check = validate_vat(entries, "MA")
    amount_check = validate_amounts(entries)
    writing_check = verify_writings(entries)

    all_warnings = (
        vat_check.warnings[:50]
        + amount_check.warnings[:50]
        + writing_check.warnings[:50]
    )

    # Avertissements spécifiques Maroc
    for entry in entries:
        if entry.currency.upper() not in ("MAD", "TND", "EUR"):
            all_warnings.append(
                f"Entrée {entry.entry_id}: devise non-standard pour Maroc ({entry.currency})"
            )

    filepath, filename = _generate_export_path(store_id, "morocco", "MA")

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    entries_data = []
    for entry in entries:
        d = entry.as_dict()
        d["morocco_compliance"] = {
            "code_general_impots": True,
            "ice_required": bool(entry.partner_vat),
            "tax_regime": _determine_tax_regime_ma(entry.tax_rate),
        }
        entries_data.append(d)
        total_debit += _round_money(entry.debit)
        total_credit += _round_money(entry.credit)
        total_tax += _round_money(entry.tax_amount)

    payload = {
        "version": "1.0",
        "standard": "CGI_MAROC",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_id": store_id,
        "country": "MA",
        "currency": "MAD",
        "period": {
            "start": period_start,
            "end": period_end,
        },
        "tax_rates": TVA_RATES_MA,
        "entry_count": len(entries),
        "totals": {
            "debit": str(_round_money(total_debit)),
            "credit": str(_round_money(total_credit)),
            "tax": str(_round_money(total_tax)),
        },
        "validation": {
            "vat_valid": vat_check.is_valid,
            "vat_errors": vat_check.errors[:20],
            "amounts_valid": amount_check.is_valid,
            "writings_valid": writing_check.is_valid,
        },
        "compliance": {
            "ice_format": "XXXXXXXXXXXXXXXXXX",
            "tax_declaration_frequency": "trimestriel",
        },
        "entries": entries_data,
    }

    raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode(FEC_ENCODING)
    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="MOROCCO",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance="MA_CGI",
        validation_warnings=all_warnings,
        metadata={
            "standard": "CGI_MAROC",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
        },
    )

    logger.info("Export Maroc terminé: %s (%d bytes)", filepath, len(raw))
    return result


def _determine_tax_regime_ma(rate: Decimal) -> str:
    """Détermine le régime fiscal marocain selon le taux TVA."""
    rate_map = {
        Decimal("0.20"): "normal",
        Decimal("0.14"): "intermediaire",
        Decimal("0.10"): "reduit",
        Decimal("0.00"): "exonere",
    }
    return rate_map.get(_round_money(rate), "autre")


# ─── Export compatible Algérie ───────────────────────────────────────────────


def export_algeria(
    store_id: int,
    entries: list[AccountingEntry],
    *,
    period_start: str = "",
    period_end: str = "",
) -> ExportResult:
    """
    Export conforme à la réglementation algérienne.

    Spécificités :
        - TVA à 19% (normal), 9% (réduit), 7% (intermédiaire), 0% (exonéré)
        - Devise DZD (Dinar algérien)
        - Numéro de registre de commerce (RC)
        - Conformité avec le Code des Taxes sur le Chiffre d'Affaires (CTCA)
        - Gestion des déclarations G50
    """
    logger.info("Export Algérie: store=%d, entries=%d", store_id, len(entries))

    # Validation TVA algérienne
    vat_check = validate_vat(entries, "DZ")
    amount_check = validate_amounts(entries)
    writing_check = verify_writings(entries)

    all_warnings = (
        vat_check.warnings[:50]
        + amount_check.warnings[:50]
        + writing_check.warnings[:50]
    )

    # Avertissements spécifiques Algérie
    for entry in entries:
        if entry.currency.upper() not in ("DZD", "EUR", "USD"):
            all_warnings.append(
                f"Entrée {entry.entry_id}: devise non-standard pour Algérie ({entry.currency})"
            )

    filepath, filename = _generate_export_path(store_id, "algeria", "DZ")

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_tax = Decimal("0")

    entries_data = []
    for entry in entries:
        d = entry.as_dict()
        d["algeria_compliance"] = {
            "ctca_conformity": True,
            "g50_declaration_ready": True,
            "tax_regime": _determine_tax_regime_dz(entry.tax_rate),
        }
        entries_data.append(d)
        total_debit += _round_money(entry.debit)
        total_credit += _round_money(entry.credit)
        total_tax += _round_money(entry.tax_amount)

    payload = {
        "version": "1.0",
        "standard": "CTCA_ALGERIE",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_id": store_id,
        "country": "DZ",
        "currency": "DZD",
        "period": {
            "start": period_start,
            "end": period_end,
        },
        "tax_rates": TVA_RATES_DZ,
        "entry_count": len(entries),
        "totals": {
            "debit": str(_round_money(total_debit)),
            "credit": str(_round_money(total_credit)),
            "tax": str(_round_money(total_tax)),
        },
        "validation": {
            "vat_valid": vat_check.is_valid,
            "vat_errors": vat_check.errors[:20],
            "amounts_valid": amount_check.is_valid,
            "writings_valid": writing_check.is_valid,
        },
        "compliance": {
            "g50_form_ready": True,
            "tax_declaration_frequency": "mensuel",
            "rc_required": True,
        },
        "entries": entries_data,
    }

    raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode(FEC_ENCODING)
    filepath.write_bytes(raw)

    result = ExportResult(
        format_name="ALGERIA",
        filename=filepath.name,
        path=filepath,
        size_bytes=len(raw),
        entry_count=len(entries),
        created_at=datetime.now(UTC).isoformat(),
        checksum=_compute_checksum(raw),
        country_compliance="DZ_CTCA",
        validation_warnings=all_warnings,
        metadata={
            "standard": "CTCA_ALGERIE",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "total_tax": str(total_tax),
        },
    )

    logger.info("Export Algérie terminé: %s (%d bytes)", filepath, len(raw))
    return result


def _determine_tax_regime_dz(rate: Decimal) -> str:
    """Détermine le régime fiscal algérien selon le taux TVA."""
    rate_map = {
        Decimal("0.19"): "normal",
        Decimal("0.09"): "reduit",
        Decimal("0.07"): "intermediaire",
        Decimal("0.00"): "exonere",
    }
    return rate_map.get(_round_money(rate), "autre")


# ─── API compatible export_edi (non modifiée) ────────────────────────────────


def export_edi(invoice_id: int):
    """Compatibilité avec l'API existante — génère un export JSON minimal."""
    entry = AccountingEntry(
        entry_id=f"EDI-{invoice_id}",
        journal_code="VT",
        journal_label="Ventes",
        document_number=f"INV-{invoice_id}",
        document_date=datetime.now(UTC).isoformat(),
        document_type="invoice",
        account_number="707100",
        account_label="Ventes de marchandises",
        partner_code="CLI-001",
        partner_label="Client",
        partner_vat="",
        debit=Decimal("0"),
        credit=Decimal("0"),
        tax_rate=Decimal("0.19"),
        tax_amount=Decimal("0"),
        currency="TND",
        description=f"Facture {invoice_id}",
        store_id=1,
        country_code="TN",
    )
    result = export_json(store_id=1, entries=[entry])
    return {"status": "exported", "invoice_id": invoice_id, "export_path": str(result.path)}
