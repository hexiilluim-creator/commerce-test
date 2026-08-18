import os

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
os.environ["ENCRYPTION_KEY"] = "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0="
os.environ["CSRF_SECRET"] = "test-csrf-secret-32-chars-minimum-ok"
os.environ["INTERNAL_HEALTH_TOKEN"] = "test-internal-token-minimum-32-chars-ok"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify"
os.environ["INSTAGRAM_VERIFY_TOKEN"] = "test-verify"
os.environ["FACEBOOK_VERIFY_TOKEN"] = "test-verify"
os.environ["TIKTOK_VERIFY_TOKEN"] = "test-verify"
os.environ["CORS_ORIGINS"] = "http://test"

import time
from unittest.mock import MagicMock

from middleware.auth import _HEALTH_DETAIL_BUCKET, _HEALTH_DETAIL_WINDOW_SECONDS, require_internal_health_rate_limit

_HEALTH_DETAIL_BUCKET.clear()
request = MagicMock()
request.client = MagicMock()
request.client.host = "127.0.0.1"
request.url = MagicMock()
request.url.path = "/api/v1/ops/health/detailed"

# First call creates bucket
require_internal_health_rate_limit(request)
print("After 1st call:", dict(_HEALTH_DETAIL_BUCKET))

# Second call should raise
try:
    require_internal_health_rate_limit(request)
    print("No exception raised!")
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")
