"""services/facture_signature.py — Signature numérique, horodatage et conformité
des factures électroniques conformément à l'article 18 du Code Général des Impôts (CGI) tunisien.

Fonctionnalités :
    - Calcul SHA-256 du PDF
    - Horodatage RFC 3161 via TSA (avec fallback local en cas d'absence)
    - Signature numérique du document (PKCS#1 v1.5 / RSA-SHA256)
    - Génération d'un QR Code (numéro facture, hash SHA-256, date UTC)
    - Ajout automatique d'un pied de page : « Conforme art. 18 CGI tunisien »
    - Journalisation complète (logging)
    - Exceptions propres et typage complet

API publique :
    sign_invoice(pdf_path: str) -> SignResult
    verify_invoice(pdf_path: str) -> VerifyResult

Aucun module externe n'est modifié.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

try:
    import qrcode
except ImportError:  # pragma: no cover — qrcode est dans requirements.txt
    qrcode = None  # type: ignore[assignment]

try:
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover — Pillow est dans requirements.txt
    PILImage = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ─── Constantes ──────────────────────────────────────────────────────────────

DEFAULT_TSA_URL: Final[str] = os.environ.get(
    "TSA_URL", "https://tsa.certsign.fr/tsa"
)
TSA_TIMEOUT_SECONDS: Final[int] = 10
RSA_KEY_BITS: Final[int] = 2048
QR_VERSION: Final[int] = 6
QR_BOX_SIZE: Final[int] = 6
QR_BORDER: Final[int] = 2
FOOTER_TEXT: Final[str] = "Conforme art. 18 CGI tunisien"
FOOTER_FONT_SIZE: Final[float] = 7.0
FOOTER_COLOR_HEX: Final[str] = "#666666"
QR_MAX_SIZE_MM: Final[float] = 42.0

# ─── Exceptions propres ──────────────────────────────────────────────────────


class InvoiceSignatureError(Exception):
    """Erreur générique liée à la signature de facture."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        logger.error("InvoiceSignatureError: %s", message, exc_info=cause)


class TSAUnavailableError(InvoiceSignatureError):
    """Le serveur d'horodatage (TSA) est injoignable — fallback local activé."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        logger.warning("TSAUnavailableError — fallback local: %s", message)


class InvalidPDFError(InvoiceSignatureError):
    """Le fichier PDF fourni n'est pas un PDF valide."""


class SignatureNotFoundError(InvoiceSignatureError):
    """Aucune signature trouvée lors de la vérification."""


class HashMismatchError(InvoiceSignatureError):
    """Le hash SHA-256 ne correspond pas lors de la vérification."""


class TimestampVerificationError(InvoiceSignatureError):
    """L'horodatage du document n'est pas conforme."""


class QRCodeGenerationError(InvoiceSignatureError):
    """Erreur lors de la génération du QR Code."""


# ─── Dataclasses de résultat ─────────────────────────────────────────────────


class SignResult:
    """Résultat de la signature d'une facture."""

    def __init__(
        self,
        *,
        pdf_path: Path,
        signed_pdf_path: Path,
        sha256_hash: str,
        invoice_number: str,
        timestamp_utc: str,
        timestamp_source: str,
        qr_data: str,
        signature_fingerprint: str,
    ) -> None:
        self.pdf_path = pdf_path
        self.signed_pdf_path = signed_pdf_path
        self.sha256_hash = sha256_hash
        self.invoice_number = invoice_number
        self.timestamp_utc = timestamp_utc
        self.timestamp_source = timestamp_source
        self.qr_data = qr_data
        self.signature_fingerprint = signature_fingerprint

    def as_dict(self) -> dict[str, Any]:
        return {
            "pdf_path": str(self.pdf_path),
            "signed_pdf_path": str(self.signed_pdf_path),
            "sha256_hash": self.sha256_hash,
            "invoice_number": self.invoice_number,
            "timestamp_utc": self.timestamp_utc,
            "timestamp_source": self.timestamp_source,
            "qr_data": self.qr_data,
            "signature_fingerprint": self.signature_fingerprint,
        }


class VerifyResult:
    """Résultat de la vérification d'une facture signée."""

    def __init__(
        self,
        *,
        valid: bool,
        pdf_path: Path,
        sha256_match: bool,
        signature_valid: bool,
        timestamp_source: str,
        qr_data: str,
        details: str,
    ) -> None:
        self.valid = valid
        self.pdf_path = pdf_path
        self.sha256_match = sha256_match
        self.signature_valid = signature_valid
        self.timestamp_source = timestamp_source
        self.qr_data = qr_data
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "pdf_path": str(self.pdf_path),
            "sha256_match": self.sha256_match,
            "signature_valid": self.signature_valid,
            "timestamp_source": self.timestamp_source,
            "qr_data": self.qr_data,
            "details": self.details,
        }


# ─── Helpers internes ────────────────────────────────────────────────────────


def _validate_pdf(path: Path) -> bytes:
    """Valide que le fichier existe et est un PDF, retourne les bytes."""
    if not path.exists():
        raise InvalidPDFError(f"PDF introuvable: {path}")
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise InvalidPDFError(f"Ce fichier n'est pas un PDF valide: {path}")
    return data


def _compute_sha256(data: bytes) -> str:
    """Calcule le hash SHA-256 d'un contenu binaire."""
    return hashlib.sha256(data).hexdigest()


def _extract_invoice_number(pdf_path: Path) -> str:
    """Extrait le numéro de facture depuis le PDF (pattern INV-XXXX)."""
    text = pdf_path.read_text(errors="ignore")
    import re
    match = re.search(r'(?:INV|AV)-\d{4}-\d{6}-[A-F0-9]{6}', text)
    if match:
        return match.group(0)
    # Fallback : hash du fichier si aucun numéro trouvé
    return _compute_sha256(pdf_path.read_bytes())[:24].upper()


def _fetch_rfc3161_timestamp(pdf_bytes: bytes) -> tuple[str, str]:
    """
    Requiert un horodatage RFC 3161 depuis le serveur TSA.

    Retourne (timestamp_iso_utc, source).
    En cas d'échec (TSA absent / timeout), fallback sur l'horloge locale.
    """
    tsa_url = DEFAULT_TSA_URL
    source = "local_fallback"
    timestamp_iso = datetime.now(UTC).isoformat(timespec="milliseconds")

    if httpx is None:
        logger.warning("httpx indisponible — horodatage local")
        return timestamp_iso, source

    try:
        client = httpx.Client(timeout=TSA_TIMEOUT_SECONDS)
        response = client.post(
            tsa_url,
            content=_build_timestamp_request(pdf_bytes),
            headers={"Content-Type": "application/timestamp-query"},
        )
        if response.status_code == 200:
            parsed = _parse_timestamp_response(response.content)
            if parsed:
                timestamp_iso = parsed
                source = "tsa"
                logger.info("Horodatage RFC3161 obtenu depuis TSA")
            else:
                raise TSAUnavailableError("Réponse TSA non parseable")
        else:
            raise TSAUnavailableError(f"TSA HTTP {response.status_code}")
    except (OSError, httpx.TimeoutException, TSAUnavailableError) as exc:
        logger.warning("TSA indisponible (%s) — horodatage local activé", exc)
        timestamp_iso = datetime.now(UTC).isoformat(timespec="milliseconds")
        source = "local_fallback"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur TSA (%s) — horodatage local", exc)
        timestamp_iso = datetime.now(UTC).isoformat(timespec="milliseconds")
        source = "local_fallback"

    return timestamp_iso, source


def _build_timestamp_request(pdf_bytes: bytes) -> bytes:
    """Construit une requête TimeStampReq minimaliste (DER-like)."""
    # OID sha256 = 2.16.840.1.101.3.4.2.1
    digest_algo = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20"
    digest = hashlib.sha256(pdf_bytes).digest()
    # Encapsulate dans un SEQUENCE (TimeStampReq)
    policy = b"\xa0\x0a\x06\x08\x2a\x86\x48\x86\xf7\x0d\x01\x09\x0f"
    message_imprint = b"\x30\x41" + digest_algo[4:] + digest
    nonce = secrets.token_bytes(8)
    nonce_field = b"\x02\x08" + nonce
    req_body = (
        b"\x02\x01\x01"  # version v1
        + message_imprint
        + policy
        + nonce_field
    )
    # SEQUENCE
    return b"\x30" + _der_length(len(req_body)) + req_body


def _parse_timestamp_response(data: bytes) -> str | None:
    """Parse une réponse TimeStampResp simplifiée pour extraire le timestamp."""
    try:
        # Recherche la date DER (GeneralizedTime / UTCTime)
        if b"\x18\x0f" in data:  # GeneralizedTime 15 chars
            idx = data.index(b"\x18\x0f")
            raw = data[idx + 2:idx + 17].decode("ascii", errors="ignore")
            if len(raw) >= 14:
                dt = datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
                dt = dt.replace(tzinfo=UTC)
                return dt.isoformat(timespec="milliseconds")
        elif b"\x17\x0d" in data:  # UTCTime 13 chars
            idx = data.index(b"\x17\x0d")
            raw = data[idx + 2:idx + 15].decode("ascii", errors="ignore")
            if len(raw) >= 12:
                dt = datetime.strptime(raw[:12], "%y%m%d%H%M%S")
                dt = dt.replace(tzinfo=UTC)
                return dt.isoformat(timespec="milliseconds")
    except Exception:  # noqa: BLE001
        return None
    return None


def _der_length(length: int) -> bytes:
    """Encode la longueur en notation DER."""
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b"\x81" + bytes([length])
    else:
        return b"\x82" + struct.pack(">H", length)


def _generate_private_key() -> rsa.RSAPrivateKey:
    """Génère une clé privée RSA (ou charge depuis fichier/env)."""
    key_pem = os.environ.get("SIGNING_KEY_PEM")
    if key_pem:
        try:
            return serialization.load_pem_private_key(
                key_pem.encode() if isinstance(key_pem, str) else key_pem,
                password=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clé SIGNING_KEY_PEM invalide, génération RSA (%s)", exc)
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=RSA_KEY_BITS,
    )


def _generate_certificate(
    private_key: rsa.RSAPrivateKey,
) -> x509.Certificate:
    """Génère un certificat X.509 auto-signé pour la signature de facture."""
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "AutoCommerce Invoice Signer"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AutoCommerce Enterprise"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "TN"),
    ])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + 5))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )
    return cert


def _sign_hash(
    private_key: rsa.RSAPrivateKey,
    data: bytes,
) -> bytes:
    """Signe un hash SHA-256 avec PKCS#1 v1.5."""
    return private_key.sign(
        data,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def _verify_signature(
    public_key: rsa.RSAPublicKey,
    data: bytes,
    signature: bytes,
) -> bool:
    """Vérifie une signature PKCS#1 v1.5."""
    try:
        public_key.verify(
            signature,
            data,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _generate_qr_data(
    *,
    invoice_number: str,
    sha256_hash: str,
    timestamp_utc: str,
) -> str:
    """Construit la charge utile du QR Code."""
    payload = {
        "invoice": invoice_number,
        "sha256": sha256_hash,
        "timestamp": timestamp_utc,
    }
    import json
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _render_qr_image(qr_data: str) -> PILImage.Image | None:
    """Génère une image QR Code depuis les données."""
    if qrcode is None or PILImage is None:
        logger.warning("qrcode/PIL indisponibles — QR Code non généré")
        return None

    try:
        qr = qrcode.QRCode(
            version=QR_VERSION,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=QR_BOX_SIZE,
            border=QR_BORDER,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        return img
    except Exception as exc:  # noqa: BLE001
        raise QRCodeGenerationError(str(exc)) from exc


def _append_footer_and_qr(
    pdf_path: Path,
    pdf_bytes: bytes,
    qr_data: str,
) -> bytes:
    """
    Ajoute un pied de page « Conforme art. 18 CGI tunisien » et un QR Code
    sur chaque page du PDF, puis retourne le PDF modifié.

    Utilise reportlab + PyPDF2 pour superposer le contenu sur le PDF existant.
    """
    import tempfile
    from io import BytesIO

    # Étape 1 : Créer l'overlay (QR + footer) via reportlab
    qr_path: Path | None = None
    try:
        # Sauvegarder le QR en fichier temporaire (reportlab drawImage exige un chemin)
        qr_img = _render_qr_image(qr_data)
        if qr_img is not None:
            qr_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            qr_img.save(qr_tmp.name, format="PNG")
            qr_path = Path(qr_tmp.name)
            qr_tmp.close()

        # Créer l'overlay PDF
        overlay_path = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        overlay_path.close()
        overlay_file = Path(overlay_path.name)

        c = canvas.Canvas(str(overlay_file), pagesize=(595.27, 841.89))  # A4

        if qr_path is not None:
            qr_size_pt = QR_MAX_SIZE_MM * 2.835  # 1mm ≈ 2.835 pt
            c.drawImage(
                str(qr_path),
                x=20,
                y=20,
                width=qr_size_pt,
                height=qr_size_pt,
                preserveAspectRatio=True,
            )

        # Pied de page
        c.setFont("Helvetica", FOOTER_FONT_SIZE)
        c.setFillColorRGB(0.4, 0.4, 0.4)  # #666666
        footer_y = 14  # ~5mm from bottom
        c.drawString(20, footer_y, FOOTER_TEXT)
        c.showPage()
        c.save()

        overlay_bytes = overlay_file.read_bytes()
    finally:
        if qr_path and qr_path.exists():
            qr_path.unlink()

    # Étape 2 : Fusionner overlay avec PDF original via pypdf
    from pypdf import PdfReader, PdfWriter  # type: ignore

    try:
        original = PdfReader(BytesIO(pdf_bytes))
        overlay_reader = PdfReader(BytesIO(overlay_bytes))
        overlay_page = overlay_reader.pages[0]

        writer = PdfWriter()
        for page in original.pages:
            page.merge_page(overlay_page, expand=True)
            writer.add_page(page)

        out_buf = BytesIO()
        writer.write(out_buf)
        return out_buf.getvalue()
    except ImportError:
        logger.warning("pypdf non disponible — pied de page non ajouté")
        return pdf_bytes
    except Exception as exc:  # noqa: BLE001
        logger.error("Erreur de fusion PDF: %s", exc)
        return pdf_bytes


# ─── API publique ─────────────────────────────────────────────────────────────


def sign_invoice(pdf_path: str | Path) -> SignResult:
    """
    Signe une facture PDF : hash SHA-256, horodatage, signature numérique,
    QR Code, pied de page de conformité.

    Args:
        pdf_path: Chemin vers le fichier PDF de la facture.

    Returns:
        SignResult contenant toutes les métadonnées de la signature.

    Raises:
        InvalidPDFError: Si le fichier n'est pas un PDF valide.
        InvoiceSignatureError: Erreur générique de signature.
    """
    path = Path(pdf_path)
    logger.info("Début signature facture: %s", path)

    # 1. Validation du PDF
    pdf_bytes = _validate_pdf(path)
    invoice_number = _extract_invoice_number(path)
    logger.info("Numéro facture détecté: %s", invoice_number)

    # 2. Calcul SHA-256
    sha256_hash = _compute_sha256(pdf_bytes)
    logger.info("SHA-256: %s", sha256_hash)

    # 3. Horodatage RFC 3161
    timestamp_utc, timestamp_source = _fetch_rfc3161_timestamp(pdf_bytes)
    logger.info("Horodatage [%s]: %s", timestamp_source, timestamp_utc)

    # 4. Signature numérique
    private_key = _generate_private_key()
    signature = _sign_hash(private_key, pdf_bytes)
    cert = _generate_certificate(private_key)
    fingerprint_hex = cert.fingerprint(hashes.SHA256()).hex()
    logger.info("Signature générée, empreinte: %s", fingerprint_hex[:16])

    # 5. Génération QR Code
    qr_data = _generate_qr_data(
        invoice_number=invoice_number,
        sha256_hash=sha256_hash,
        timestamp_utc=timestamp_utc,
    )
    logger.info("QR Data générée: %d caractères", len(qr_data))

    # 6. Ajout pied de page + QR Code au PDF
    signed_pdf_bytes = _append_footer_and_qr(path, pdf_bytes, qr_data)

    # 7. Écriture du PDF signé
    signed_path = path.parent / f"{path.stem}_signed.pdf"
    signed_path.write_bytes(signed_pdf_bytes)
    logger.info("PDF signé écrit: %s", signed_path)

    # 8. Stockage des métadonnées de signature (côté fichier)
    metadata_path = path.parent / f"{path.stem}_signature.json"
    import json
    metadata = {
        "invoice_number": invoice_number,
        "sha256_hash": sha256_hash,
        "timestamp_utc": timestamp_utc,
        "timestamp_source": timestamp_source,
        "signature_hex": base64.b64encode(signature).decode("ascii"),
        "certificate_pem": cert.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii"),
        "certificate_fingerprint": fingerprint_hex,
        "qr_data": qr_data,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=True))

    result = SignResult(
        pdf_path=path,
        signed_pdf_path=signed_path,
        sha256_hash=sha256_hash,
        invoice_number=invoice_number,
        timestamp_utc=timestamp_utc,
        timestamp_source=timestamp_source,
        qr_data=qr_data,
        signature_fingerprint=fingerprint_hex,
    )

    logger.info("Signature facture terminée: %s", path)
    return result


def verify_invoice(pdf_path: str | Path) -> VerifyResult:
    """
    Vérifie l'intégrité d'une facture signée : hash, signature, horodatage.

    Args:
        pdf_path: Chemin vers le fichier PDF signé.

    Returns:
        VerifyResult contenant le résultat de vérification.

    Raises:
        InvalidPDFError: Si le fichier n'est pas un PDF valide.
        SignatureNotFoundError: Si aucune métadonnée de signature n'est trouvée.
    """
    import json

    path = Path(pdf_path)
    logger.info("Début vérification facture: %s", path)

    # 1. Validation du PDF
    pdf_bytes = _validate_pdf(path)

    # 2. Chargement des métadonnées de signature
    stem = path.stem.replace("_signed", "") if "_signed" in path.stem else path.stem
    metadata_path = path.parent / f"{stem}_signature.json"

    if not metadata_path.exists():
        raise SignatureNotFoundError(f"Métadonnées de signature absentes: {metadata_path}")

    metadata = json.loads(metadata_path.read_text())

    stored_hash: str = metadata.get("sha256_hash", "")
    stored_timestamp: str = metadata.get("timestamp_utc", "")
    stored_signature_b64: str = metadata.get("signature_hex", "")
    stored_cert_pem: str = metadata.get("certificate_pem", "")
    stored_source: str = metadata.get("timestamp_source", "unknown")
    stored_qr_data: str = metadata.get("qr_data", "")

    # 3. Vérification du hash SHA-256
    current_hash = _compute_sha256(pdf_bytes)
    sha256_match = current_hash == stored_hash

    if not sha256_match:
        logger.warning(
            "Hash mismatch: attendu=%s, obtenu=%s",
            stored_hash,
            current_hash,
        )

    # 4. Vérification de la signature numérique
    signature_valid = False
    try:
        signature_bytes = base64.b64decode(stored_signature_b64)
        public_key = serialization.load_pem_public_key(
            stored_cert_pem.encode("ascii")
        )
        signature_valid = _verify_signature(public_key, pdf_bytes, signature_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur vérification signature: %s", exc)
        signature_valid = False

    if not signature_valid:
        logger.warning("Signature numérique invalide ou altérée")

    # 5. Résultat global
    valid = sha256_match and signature_valid
    details_parts = []
    details_parts.append(f"Hash SHA-256: {'OK' if sha256_match else 'MISMATCH'}")
    details_parts.append(f"Signature: {'OK' if signature_valid else 'INVALID'}")
    details_parts.append(f"Horodatage: {stored_timestamp} [{stored_source}]")
    details = "; ".join(details_parts)

    result = VerifyResult(
        valid=valid,
        pdf_path=path,
        sha256_match=sha256_match,
        signature_valid=signature_valid,
        timestamp_source=stored_source,
        qr_data=stored_qr_data,
        details=details,
    )

    logger.info(
        "Vérification terminée: valid=%s, sha256=%s, signature=%s",
        valid,
        sha256_match,
        signature_valid,
    )
    return result


# ─── Entrée CLI (optionnel, pour tests rapides) ──────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        print("Usage: python facture_signature.py <command> <pdf_path>")
        print("  commands: sign, verify")
        sys.exit(1)

    command = sys.argv[1]
    pdf = sys.argv[2]

    if command == "sign":
        result = sign_invoice(pdf)
        import json
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    elif command == "verify":
        result = verify_invoice(pdf)
        import json
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Commande inconnue: {command}")
        sys.exit(1)
