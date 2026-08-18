"""services/upload_security.py — Validation et stockage sécurisé des fichiers."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

from config import settings

MAX_UPLOAD_SIZE = 10 * 1024 * 1024

# AUDIT FIX : les 3 appelants réels (product_images.py, ai.py, expenses.py)
# passent tous `allow="image"` ou `allow="document"` (alias courts), jamais
# le type MIME complet. La fonction n'acceptait que des types MIME/"image/*"
# exacts — chaque appel levait donc TypeError/valeur non reconnue. Les alias
# courts sont maintenant la voie principale ; les types MIME exacts restent
# acceptés pour rétrocompatibilité.
ALLOW_ALIASES: dict[str, set[str]] = {
    "image": {"image/jpeg", "image/png", "image/webp", "image/gif"},
    "document": {"application/pdf"},
    "image/*": {"image/jpeg", "image/png", "image/webp", "image/gif"},
    "application/pdf": {"application/pdf"},
}


class UploadRejected(Exception):
    """Levée si le fichier uploadé est rejeté pour raison de sécurité."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _normalize_allow(allow: str | list[str] | None) -> set[str]:
    if allow is None:
        allow = ["image", "document"]
    if isinstance(allow, str):
        allow = [allow]
    normalized: set[str] = set()
    for item in allow:
        if item in ALLOW_ALIASES:
            normalized.update(ALLOW_ALIASES[item])
        else:
            normalized.add(item)
    return normalized


def _detect_mime_type(data: bytes) -> str:
    """Détection par magic bytes — le content_type fourni par le client n'est
    jamais fait confiance (spoofable), seul le contenu réel du fichier compte."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    raise UploadRejected("Invalid file signature")


def validate_upload(
    data: bytes,
    filename: str,
    content_type: str | None = None,  # informationnel seul, jamais fait confiance
    tenant_id: int | None = None,  # non utilisé ici, accepté pour compat avec validate_and_store
    allow: str | list[str] = "image",
    max_bytes: int | None = None,
) -> str:
    """Valide la taille et les magic bytes, retourne le vrai MIME détecté."""
    size_limit = max_bytes if max_bytes is not None else MAX_UPLOAD_SIZE
    if not data:
        raise UploadRejected("Empty file")
    if len(data) >= size_limit:
        raise UploadRejected(f"File exceeds {size_limit // (1024 * 1024)}MB limit")

    detected_mime = _detect_mime_type(data)
    allowed = _normalize_allow(allow)
    if detected_mime not in allowed:
        raise UploadRejected(f"MIME type {detected_mime} not allowed for {filename}")
    return detected_mime


async def validate_and_store(
    data: bytes,
    filename: str,
    tenant_id: int,
    content_type: str | None = None,
    allow: str | list[str] = "image",
    max_bytes: int | None = None,
) -> dict:
    """Valide le fichier puis le stocke sur S3 si configuré, sinon en local sous /tmp/uploads."""
    detected_mime = validate_upload(
        data=data, filename=filename, content_type=content_type,
        tenant_id=tenant_id, allow=allow, max_bytes=max_bytes,
    )
    safe_name = os.path.basename(filename) or "upload.bin"
    object_name = f"{uuid.uuid4().hex}_{safe_name}"

    bucket = (getattr(settings, "S3_BUCKET", "") or "").strip()
    s3_endpoint = (getattr(settings, "S3_ENDPOINT", "") or "").strip()
    access_key = (getattr(settings, "S3_ACCESS_KEY", "") or "").strip()
    secret_key = (getattr(settings, "S3_SECRET_KEY", "") or "").strip()

    if bucket:
        try:
            import boto3

            client_kwargs = {
                "region_name": getattr(settings, "S3_REGION", "us-east-1"),
                "aws_access_key_id": access_key or None,
                "aws_secret_access_key": secret_key or None,
            }
            if s3_endpoint:
                client_kwargs["endpoint_url"] = s3_endpoint

            s3_client = boto3.client("s3", **client_kwargs)
            key = f"uploads/{tenant_id}/{object_name}"
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=detected_mime,
            )

            public_url = (getattr(settings, "S3_PUBLIC_URL", "") or "").strip()
            if public_url:
                url = f"{public_url.rstrip('/')}/{key}"
            elif s3_endpoint:
                url = f"{s3_endpoint.rstrip('/')}/{bucket}/{key}"
            else:
                url = None

            return {
                "url": url,
                "stored": True,
                "filename": safe_name,
                "size": len(data),
                "mime_type": detected_mime,
                "storage_key": key,
                "storage_backend": "s3",
            }
        except Exception as _exc:
            logger.warning("operation failed: %s", _exc)
            # En dev/CI, boto3 ou le backend S3 peut être absent : fallback local.
            pass

    target_dir = Path("/tmp/uploads") / str(tenant_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / object_name
    target_path.write_bytes(data)

    return {
        "url": str(target_path),
        "stored": True,
        "filename": safe_name,
        "size": len(data),
        "mime_type": detected_mime,
        "storage_key": str(target_path),
        "storage_backend": "local",
    }
