from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.upload_security import UploadRejected, validate_and_store, validate_upload


def test_validate_upload_accepts_real_magic_bytes_and_aliases():
    assert validate_upload(b"\xff\xd8\xffjpeg", "a.jpg", allow="image") == "image/jpeg"
    assert validate_upload(b"\x89PNG\r\n\x1a\n", "a.png", allow="image") == "image/png"
    assert validate_upload(b"GIF89a", "a.gif", allow="image/*") == "image/gif"
    assert validate_upload(b"%PDF-1.7", "a.pdf", allow="document") == "application/pdf"


def test_validate_upload_rejects_empty_oversize_invalid_and_disallowed_files():
    with pytest.raises(UploadRejected, match="Empty"):
        validate_upload(b"", "empty.jpg")
    with pytest.raises(UploadRejected, match="exceeds"):
        validate_upload(b"\xff\xd8\xff", "large.jpg", max_bytes=3)
    with pytest.raises(UploadRejected, match="Invalid file signature"):
        validate_upload(b"not-a-file", "x.jpg")
    with pytest.raises(UploadRejected, match="not allowed"):
        validate_upload(b"%PDF-1.7", "x.pdf", allow="image")


@pytest.mark.asyncio
async def test_validate_and_store_uses_local_fallback_and_sanitizes_filename(tmp_path):
    settings = SimpleNamespace(S3_BUCKET="", S3_ENDPOINT="", S3_ACCESS_KEY="", S3_SECRET_KEY="")
    with patch("services.upload_security.settings", settings), patch(
        "services.upload_security.Path", wraps=Path
    ):
        # Use the production path but assert basename sanitization and response shape.
        result = await validate_and_store(b"\x89PNG\r\n\x1a\n", "../../safe.png", 9, allow="image")
    assert result["stored"] is True
    assert result["storage_backend"] == "local"
    assert result["filename"] == "safe.png"
    assert result["mime_type"] == "image/png"
    assert Path(result["storage_key"]).read_bytes() == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_validate_and_store_uses_s3_and_public_url():
    settings = SimpleNamespace(
        S3_BUCKET="bucket",
        S3_ENDPOINT="https://s3.test",
        S3_ACCESS_KEY="access",
        S3_SECRET_KEY="secret",
        S3_REGION="eu",
        S3_PUBLIC_URL="https://cdn.test",
    )
    client = MagicMock()
    with patch("services.upload_security.settings", settings), patch("boto3.client", return_value=client):
        result = await validate_and_store(b"%PDF-1.7", "invoice.pdf", 3, allow="document")
    assert result["storage_backend"] == "s3"
    assert result["url"].startswith("https://cdn.test/uploads/3/")
    client.put_object.assert_called_once()
    assert client.put_object.call_args.kwargs["ContentType"] == "application/pdf"


@pytest.mark.asyncio
async def test_validate_and_store_falls_back_local_when_s3_put_fails():
    settings = SimpleNamespace(
        S3_BUCKET="bucket", S3_ENDPOINT="", S3_ACCESS_KEY="", S3_SECRET_KEY="", S3_REGION="us"
    )
    client = MagicMock()
    client.put_object.side_effect = RuntimeError("s3 down")
    with patch("services.upload_security.settings", settings), patch("boto3.client", return_value=client):
        result = await validate_and_store(b"\xff\xd8\xffjpeg", "photo.jpg", 4, allow="image")
    assert result["storage_backend"] == "local"
    assert Path(result["storage_key"]).exists()
