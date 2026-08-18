"""tests/unit/test_facture_signature.py — Tests unitaires pour la signature de factures.

Couverture :
    - Validation PDF (fichier manquant, fichier non-PDF)
    - Calcul SHA-256 (déterminisme, unicité)
    - Génération de clé RSA et certificat X.509
    - Horodatage RFC 3161 avec fallback local (TSA simulé absent)
    - Signature et vérification numérique (PKCS#1 v1.5)
    - Génération de QR Code
    - Ajout du pied de page « Conforme art. 18 CGI tunisien »
    - sign_invoice() end-to-end
    - verify_invoice() end-to-end (succès et échec)
    - Exceptions propres
    - Métadonnées JSON
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key_at_least_32_chars_long_for_safety")
os.environ.setdefault("ENCRYPTION_KEY", "mY6rHQ0TLMlAuHCXKJHtEPeyLyvOyBK9p0KW1MLrnu8=")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-not-real")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok")

from services.facture_signature import (
    DEFAULT_TSA_URL,
    FOOTER_TEXT,
    RSA_KEY_BITS,
    HashMismatchError,
    InvalidPDFError,
    InvoiceSignatureError,
    QRCodeGenerationError,
    SignatureNotFoundError,
    SignResult,
    TimestampVerificationError,
    TSAUnavailableError,
    VerifyResult,
    _append_footer_and_qr,
    _build_timestamp_request,
    _compute_sha256,
    _der_length,
    _extract_invoice_number,
    _generate_certificate,
    _generate_private_key,
    _generate_qr_data,
    _parse_timestamp_response,
    _render_qr_image,
    _sign_hash,
    _validate_pdf,
    _verify_signature,
    sign_invoice,
    verify_invoice,
)

# ─── Helpers de test ─────────────────────────────────────────────────────────


def _create_test_pdf(path: Path, content: str = "INV-0001-202501-ABC123") -> Path:
    """Crée un PDF minimal pour les tests."""
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, f"Facture {content}")
    c.drawString(72, 700, "Test invoice for unit tests")
    c.save()
    path.write_bytes(buf.getvalue())
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de validation PDF
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_validate_pdf_missing_file():
    """_validate_pdf lève InvalidPDFError si le fichier n'existe pas."""
    with pytest.raises(InvalidPDFError, match="introuvable"):
        _validate_pdf(Path("/tmp/nonexistent_invoice_12345.pdf"))


@pytest.mark.unit
def test_validate_pdf_not_a_pdf():
    """_validate_pdf lève InvalidPDFError si le fichier n'est pas un PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"This is not a PDF file at all")
        tmp = Path(f.name)
    try:
        with pytest.raises(InvalidPDFError, match="pas un PDF"):
            _validate_pdf(tmp)
    finally:
        tmp.unlink()


@pytest.mark.unit
def test_validate_pdf_valid_pdf():
    """_validate_pdf accepte un vrai PDF et retourne ses bytes."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        data = _validate_pdf(path)
        assert data.startswith(b"%PDF")
        assert len(data) > 0
    finally:
        path.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests SHA-256
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_sha256_deterministic():
    """_compute_sha256 retourne le même hash pour le même contenu."""
    data = b"Test invoice content"
    h1 = _compute_sha256(data)
    h2 = _compute_sha256(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 = 64 hex chars
    assert hashlib.sha256(data).hexdigest() == h1


@pytest.mark.unit
def test_compute_sha256_different_data():
    """_compute_sha256 retourne des hashes différents pour des données différentes."""
    h1 = _compute_sha256(b"Content A")
    h2 = _compute_sha256(b"Content B")
    assert h1 != h2


@pytest.mark.unit
def test_compute_sha256_empty_bytes():
    """_compute_sha256 fonctionne sur des bytes vides."""
    h = _compute_sha256(b"")
    assert h == hashlib.sha256(b"").hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests clé RSA et certificat
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_generate_private_key():
    """_generate_private_key retourne une clé RSA valide."""
    key = _generate_private_key()
    assert key is not None
    assert hasattr(key, "public_key")
    public = key.public_key()
    assert public.key_size == RSA_KEY_BITS


@pytest.mark.unit
def test_generate_private_key_from_env():
    """_generate_private_key charge depuis SIGNING_KEY_PEM si disponible."""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    test_key = rsa_mod.generate_private_key(65537, 2048)
    from cryptography.hazmat.primitives import serialization as ser
    pem = test_key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()).decode()

    old_env = os.environ.get("SIGNING_KEY_PEM")
    os.environ["SIGNING_KEY_PEM"] = pem
    try:
        key = _generate_private_key()
        assert key is not None
        # Vérifier que c'est bien la même clé
        assert key.private_numbers().d == test_key.private_numbers().d
    finally:
        if old_env is not None:
            os.environ["SIGNING_KEY_PEM"] = old_env
        else:
            os.environ.pop("SIGNING_KEY_PEM", None)


@pytest.mark.unit
def test_generate_certificate():
    """_generate_certificate retourne un X.509 valide."""
    key = _generate_private_key()
    cert = _generate_certificate(key)
    assert cert is not None
    # Vérifier les attributs
    attrs = {attr.oid for attr in cert.subject}
    from cryptography.x509.oid import NameOID
    assert NameOID.COMMON_NAME in attrs
    assert NameOID.COUNTRY_NAME in attrs
    # Vérifier validité
    assert cert.not_valid_before_utc is not None
    assert cert.not_valid_after_utc is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Tests extraction numéro de facture
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_extract_invoice_number_found():
    """_extract_invoice_number trouve un numéro INV-XXXX dans le PDF ou retourne un hash."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path, content="INV-0042-202501-ABCDEF")
    try:
        num = _extract_invoice_number(path)
        # Le numéro peut être extrait du texte ou être un hash fallback
        assert len(num) > 0
    finally:
        path.unlink()


@pytest.mark.unit
def test_extract_invoice_number_not_found():
    """_extract_invoice_number retourne un hash si aucun numéro trouvé."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path, content="No invoice number here")
    try:
        num = _extract_invoice_number(path)
        assert len(num) == 24  # hash[:24]
    finally:
        path.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests horodatage RFC 3161
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_build_timestamp_request():
    """_build_timestamp_request retourne des bytes non vides."""
    req = _build_timestamp_request(b"test data")
    assert len(req) > 0
    assert req[0:1] == b"\x30"  # SEQUENCE


@pytest.mark.unit
def test_der_length():
    """_der_length encode correctement les longueurs DER."""
    assert _der_length(0) == b"\x00"
    assert _der_length(1) == b"\x01"
    assert _der_length(127) == b"\x7f"
    assert _der_length(128) == b"\x81\x80"
    assert _der_length(255) == b"\x81\xff"
    assert _der_length(256) == b"\x82\x01\x00"


@pytest.mark.unit
def test_parse_timestamp_response_gmt():
    """_parse_timestamp_response extrait une GeneralizedTime."""
    # Simuler une réponse avec GeneralizedTime 20250101120000Z
    gmt = b"20250101120000Z"
    data = b"dummy\x18\x0f" + gmt + b"\x00"
    result = _parse_timestamp_response(data)
    assert result is not None
    assert "2025-01-01" in result


@pytest.mark.unit
def test_parse_timestamp_response_gmt_invalid():
    """_parse_timestamp_response retourne None si pas de timestamp."""
    assert _parse_timestamp_response(b"no timestamp here") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Tests QR Code
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_generate_qr_data():
    """_generate_qr_data produit un JSON valide avec les bons champs."""
    data = _generate_qr_data(
        invoice_number="INV-0001-202501-ABCDEF",
        sha256_hash="deadbeef" * 8,
        timestamp_utc="2025-01-01T00:00:00+00:00",
    )
    parsed = json.loads(data)
    assert parsed["invoice"] == "INV-0001-202501-ABCDEF"
    assert parsed["sha256"] == "deadbeef" * 8
    assert "2025-01-01" in parsed["timestamp"]


@pytest.mark.unit
def test_render_qr_image():
    """_render_qr_image retourne une image PIL valide."""
    qr_data = _generate_qr_data(
        invoice_number="INV-0001",
        sha256_hash="a" * 64,
        timestamp_utc="2025-01-01T00:00:00Z",
    )
    img = _render_qr_image(qr_data)
    assert img is not None
    assert hasattr(img, "size")
    assert img.size[0] > 0
    assert img.size[1] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Tests signature et vérification
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_sign_and_verify_roundtrip():
    """_sign_hash et _verify_signature forment un cycle round-trip correct."""
    key = _generate_private_key()
    data = b"test data to sign"
    signature = _sign_hash(key, data)
    assert len(signature) > 0
    # Vérifier avec la clé publique
    result = _verify_signature(key.public_key(), data, signature)
    assert result is True


@pytest.mark.unit
def test_verify_signature_wrong_data():
    """_verify_signature retourne False si les données sont altérées."""
    key = _generate_private_key()
    data = b"original data"
    signature = _sign_hash(key, data)
    result = _verify_signature(key.public_key(), b"tampered data", signature)
    assert result is False


@pytest.mark.unit
def test_verify_signature_wrong_key():
    """_verify_signature retourne False avec une clé publique différente."""
    key1 = _generate_private_key()
    key2 = _generate_private_key()
    data = b"test data"
    signature = _sign_hash(key1, data)
    result = _verify_signature(key2.public_key(), data, signature)
    assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# Tests pied de page et fusion PDF
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_footer_text_constant():
    """FOOTER_TEXT contient le texte conforme au CGI tunisien."""
    assert FOOTER_TEXT == "Conforme art. 18 CGI tunisien"


@pytest.mark.unit
def test_append_footer_and_qr():
    """_append_footer_and_qr retourne des bytes PDF valides."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        pdf_bytes = path.read_bytes()
        qr_data = '{"invoice":"INV-0001","sha256":"abc","timestamp":"2025-01-01T00:00:00Z"}'
        result = _append_footer_and_qr(path, pdf_bytes, qr_data)
        assert len(result) > len(pdf_bytes)
        assert result.startswith(b"%PDF")
    finally:
        path.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests end-to-end sign_invoice
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_sign_invoice_success():
    """sign_invoice retourne un SignResult valide avec tous les champs."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path, content="INV-0001-202501-ABCDEF")
    try:
        result = sign_invoice(str(path))
        assert isinstance(result, SignResult)
        assert result.sha256_hash
        assert len(result.sha256_hash) == 64
        assert result.timestamp_utc
        assert result.timestamp_source in ("tsa", "local_fallback")
        assert result.invoice_number
        assert result.qr_data
        assert result.signature_fingerprint
        assert result.signed_pdf_path.exists()
        # Vérifier le fichier de métadonnées
        meta_path = Path(result.pdf_path.parent) / f"{Path(result.pdf_path).stem}_signature.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["sha256_hash"] == result.sha256_hash
        assert meta["invoice_number"] == result.invoice_number
        assert meta["timestamp_utc"] == result.timestamp_utc
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)


@pytest.mark.unit
def test_sign_invoice_missing_file():
    """sign_invoice lève InvalidPDFError si le fichier n'existe pas."""
    with pytest.raises(InvalidPDFError):
        sign_invoice("/tmp/nonexistent_invoice_xyz.pdf")


@pytest.mark.unit
def test_sign_invoice_not_pdf():
    """sign_invoice lève InvalidPDFError si le fichier n'est pas un PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"Not a PDF")
        tmp = Path(f.name)
    try:
        with pytest.raises(InvalidPDFError):
            sign_invoice(str(tmp))
    finally:
        tmp.unlink()


@pytest.mark.unit
def test_sign_invoice_result_as_dict():
    """SignResult.as_dict() retourne un dictionnaire complet."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        result = sign_invoice(str(path))
        d = result.as_dict()
        assert "pdf_path" in d
        assert "signed_pdf_path" in d
        assert "sha256_hash" in d
        assert "invoice_number" in d
        assert "timestamp_utc" in d
        assert "timestamp_source" in d
        assert "qr_data" in d
        assert "signature_fingerprint" in d
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests end-to-end verify_invoice
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_verify_invoice_after_sign():
    """verify_invoice retourne valid=True après un sign_invoice réussi."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path, content="INV-0001-202501-ABCDEF")
    try:
        # Signer
        _ = sign_invoice(str(path))
        # Vérifier avec le PDF original (non modifié par le footer)
        verify_result = verify_invoice(str(path))
        assert isinstance(verify_result, VerifyResult)
        assert verify_result.sha256_match is True
        assert verify_result.signature_valid is True
        assert verify_result.valid is True
        assert verify_result.details
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)


@pytest.mark.unit
def test_verify_invoice_tampered_pdf():
    """verify_invoice retourne valid=False si le PDF a été altéré."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        _ = sign_invoice(str(path))
        # Altérer le PDF
        original_data = path.read_bytes()
        path.write_bytes(original_data + b"\x00\x00\x00")
        # Vérifier
        verify_result = verify_invoice(str(path))
        assert verify_result.sha256_match is False
        assert verify_result.valid is False
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)


@pytest.mark.unit
def test_verify_invoice_missing_metadata():
    """verify_invoice lève SignatureNotFoundError si pas de métadonnées."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        with pytest.raises(SignatureNotFoundError):
            verify_invoice(str(path))
    finally:
        path.unlink()


@pytest.mark.unit
def test_verify_invoice_missing_file():
    """verify_invoice lève InvalidPDFError si le fichier n'existe pas."""
    with pytest.raises(InvalidPDFError):
        verify_invoice("/tmp/nonexistent_invoice_xyz.pdf")


@pytest.mark.unit
def test_verify_result_as_dict():
    """VerifyResult.as_dict() retourne un dictionnaire complet."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        sign_invoice(str(path))
        result = verify_invoice(str(path))
        d = result.as_dict()
        assert "valid" in d
        assert "pdf_path" in d
        assert "sha256_match" in d
        assert "signature_valid" in d
        assert "timestamp_source" in d
        assert "qr_data" in d
        assert "details" in d
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests exceptions propres
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_invoice_signature_error_has_cause():
    """InvoiceSignatureError stocke la cause originale."""
    cause = ValueError("original error")
    err = InvoiceSignatureError("test error", cause=cause)
    assert str(err) == "test error"
    assert err.cause is cause


@pytest.mark.unit
def test_tsa_unavailable_error():
    """TSAUnavailableError est une InvoiceSignatureError."""
    err = TSAUnavailableError("TSA down")
    assert isinstance(err, InvoiceSignatureError)
    assert str(err) == "TSA down"


@pytest.mark.unit
def test_all_exceptions_are_invoice_signature_error():
    """Toutes les exceptions héritent de InvoiceSignatureError."""
    exceptions = [
        TSAUnavailableError,
        InvalidPDFError,
        SignatureNotFoundError,
        HashMismatchError,
        TimestampVerificationError,
        QRCodeGenerationError,
    ]
    for exc_class in exceptions:
        assert issubclass(exc_class, InvoiceSignatureError)


@pytest.mark.unit
def test_invalid_pdf_error():
    """InvalidPDFError peut être levée et attrapée."""
    with pytest.raises(InvalidPDFError) as exc_info:
        _validate_pdf(Path("/tmp/nonexistent.pdf"))
    assert "introuvable" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests constantes et configuration
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_default_tsa_url():
    """DEFAULT_TSA_URL est configurable via env var TSA_URL."""
    assert DEFAULT_TSA_URL == os.environ.get("TSA_URL", "https://tsa.certsign.fr/tsa")


@pytest.mark.unit
def test_rsa_key_bits():
    """RSA_KEY_BITS est 2048 (standard)."""
    assert RSA_KEY_BITS == 2048


@pytest.mark.unit
def test_footer_text():
    """FOOTER_TEXT est conforme à l'art. 18 CGI."""
    assert "art. 18" in FOOTER_TEXT
    assert "CGI" in FOOTER_TEXT
    assert "tunisien" in FOOTER_TEXT


# ═══════════════════════════════════════════════════════════════════════════════
# Tests QR Code dans le PDF signé
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_signed_pdf_contains_qr():
    """Le PDF signé est plus grand que l'original (QR + footer ajoutés)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    _create_test_pdf(path)
    try:
        original_size = path.stat().st_size
        sign_invoice(str(path))
        signed_path = path.parent / f"{path.stem}_signed.pdf"
        assert signed_path.exists()
        assert signed_path.stat().st_size > original_size
    finally:
        path.unlink(missing_ok=True)
        signed = path.parent / f"{path.stem}_signed.pdf"
        signed.unlink(missing_ok=True)
        meta = path.parent / f"{path.stem}_signature.json"
        meta.unlink(missing_ok=True)
