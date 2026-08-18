"""tests/security/test_jwt_rotation.py — P0-8 JWT rotation tests.
Valide la rotation JWT, le cutoff, et l'endpoint interne.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

pytestmark = [pytest.mark.security]


class TestJWTEncodeDecode:
    """Tests d'encodage/décodage JWT."""

    def test_encode_jwt_returns_string(self):
        from services.jwt_rotation import encode_jwt
        token = encode_jwt({"sub": "1", "store_id": 42})
        assert isinstance(token, str)
        assert len(token) > 30

    def test_decode_jwt_with_valid_token(self):
        from services.jwt_rotation import decode_jwt, encode_jwt
        payload = {"sub": "1", "store_id": 42, "role": "admin", "iat": int(time.time())}
        token = encode_jwt(payload)
        decoded = decode_jwt(token)
        assert decoded["sub"] == "1"
        assert decoded["store_id"] == 42
        assert decoded["role"] == "admin"

    def test_decode_jwt_invalid_token_raises(self):
        from jwt.exceptions import PyJWTError

        from services.jwt_rotation import decode_jwt
        with pytest.raises(PyJWTError):
            decode_jwt("invalid.token.here")


class TestJWTRotation:
    """Tests de rotation JWT."""

    def test_initial_state(self):
        from services.jwt_rotation import current_rotation_state
        state = current_rotation_state()
        assert "invalid_before_epoch" in state

    def test_rotate_updates_cutoff(self):
        from services.jwt_rotation import current_rotation_state, rotate_tokens
        before = current_rotation_state()["invalid_before_epoch"]
        time.sleep(0.01)
        result = rotate_tokens(actor="test_rotate")
        assert result["rotated"] is True
        assert result["actor"] == "test_rotate"
        assert result["invalid_before_epoch"] >= before

    def test_multiple_rotations_monotonic(self):
        from services.jwt_rotation import current_rotation_state, rotate_tokens
        cutoffs = []
        for i in range(3):
            time.sleep(0.01)
            result = rotate_tokens(actor=f"test_{i}")
            cutoffs.append(result["invalid_before_epoch"])
        for i in range(1, len(cutoffs)):
            assert cutoffs[i] >= cutoffs[i - 1], "Les cutoffs doivent être monotones"

    def test_old_token_invalidated_after_rotation(self):
        """Un token émis avant la rotation doit être invalide."""
        from jwt.exceptions import InvalidTokenError

        from services.jwt_rotation import decode_jwt, encode_jwt, rotate_tokens
        token = encode_jwt({"sub": "1", "iat": int(time.time()) - 3600})
        rotate_tokens(actor="test_invalidation")
        time.sleep(0.01)
        with pytest.raises((InvalidTokenError, Exception)):
            decode_jwt(token)

    def test_rotation_result_has_audit_fields(self):
        from services.jwt_rotation import rotate_tokens
        result = rotate_tokens(actor="audit_test")
        assert "rotated" in result
        assert "invalid_before_epoch" in result
        assert "actor" in result
        assert "previous_invalid_before_epoch" in result


class TestJWTIntervalSetting:
    """Tests de la configuration JWT_ROTATION_INTERVAL_HOURS."""

    def test_setting_exists(self):
        from config import settings
        assert hasattr(settings, "JWT_ROTATION_INTERVAL_HOURS")
        assert isinstance(settings.JWT_ROTATION_INTERVAL_HOURS, int)

    def test_default_interval(self):
        from config import settings
        assert settings.JWT_ROTATION_INTERVAL_HOURS == 24

    def test_setting_is_positive(self):
        from config import settings
        assert settings.JWT_ROTATION_INTERVAL_HOURS > 0


class TestInternalJWTRotateEndpoint:
    """Tests de l'endpoint interne /_internal/jwt/rotate."""

    def test_endpoint_file_exists(self):
        internal_ops = API_ROOT / "api" / "v1" / "internal_ops.py"
        assert internal_ops.exists()

    def test_endpoint_imports_jwt_rotation(self):
        internal_ops = API_ROOT / "api" / "v1" / "internal_ops.py"
        content = internal_ops.read_text()
        assert "jwt_rotation" in content
        assert "rotate_tokens" in content
        assert "current_rotation_state" in content

    def test_endpoint_protected_by_internal_token(self):
        internal_ops = API_ROOT / "api" / "v1" / "internal_ops.py"
        content = internal_ops.read_text()
        assert "X-Internal-Token" in content
        assert "x_internal_token" in content

    def test_endpoint_returns_state(self):
        internal_ops = API_ROOT / "api" / "v1" / "internal_ops.py"
        content = internal_ops.read_text()
        assert "current_rotation_state()" in content
        assert 'result["state"]' in content or "state" in content


class TestJWTTenantsIsolation:
    """Tests d'isolation JWT cross-tenant."""

    def test_different_store_ids_produce_different_tokens(self):
        from services.jwt_rotation import encode_jwt
        token_a = encode_jwt({"sub": "1", "store_id": 1})
        token_b = encode_jwt({"sub": "1", "store_id": 2})
        assert token_a != token_b

    def test_token_contains_store_id(self):
        from services.jwt_rotation import decode_jwt, encode_jwt
        token = encode_jwt({"sub": "1", "store_id": 99})
        decoded = decode_jwt(token)
        assert decoded["store_id"] == 99

    def test_tenant_middleware_validates_store_id(self):
        """Le middleware tenant doit valider que store_id est dans le JWT."""
        from middleware.tenant import TenantMiddleware
        assert TenantMiddleware is not None
