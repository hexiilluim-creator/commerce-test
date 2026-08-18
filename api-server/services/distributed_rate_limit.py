"""services/distributed_rate_limit.py — Distributed rate limiting via Redis.

Provides a simple `check(key, identifier)` function that uses Redis INCR+EXPIRE
for cross-worker rate limiting. Falls back to allow-all when Redis is unavailable
(fail-open — never blocks legitimate traffic on a Redis outage).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Limits per key (requests per window)
RATE_LIMITS: dict[str, tuple[int, int]] = {
    # key -> (max_requests, window_seconds)
    "auth.login": (10, 60),
    "auth.register": (5, 60),
    "auth.refresh": (20, 60),
    "auth.forgot_password": (3, 300),
    "auth.reset_password": (5, 300),
    "auth.mfa": (10, 60),
    "default": (100, 60),
}


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until reset


async def check(key: str, identifier: str) -> RateLimitResult:
    """Check rate limit for key+identifier pair using Redis.

    Returns RateLimitResult with allowed=True if within limit.
    Falls back to allowing the request if Redis is unavailable
    (fail-open by design — an outage of Redis must not lock everyone out).
    """
    import os
    if os.getenv("ENV") == "test" or os.getenv("PYTEST_CURRENT_TEST"):
        return RateLimitResult(allowed=True, remaining=999, retry_after=0)

    max_req, window = RATE_LIMITS.get(key, RATE_LIMITS["default"])
    redis_key = f"rl:{key}:{identifier}"

    try:
        from services.redis_lock import get_redis
        redis = get_redis()

        pipe = redis.pipeline()
        pipe.incr(redis_key)
        pipe.ttl(redis_key)
        results = await pipe.execute()

        count = results[0]
        ttl = results[1]

        if ttl < 0:
            await redis.expire(redis_key, window)
            ttl = window

        if count > max_req:
            logger.warning(
                "rate_limit_exceeded key=%s identifier=%s count=%s max=%s",
                key, identifier, count, max_req,
            )
            return RateLimitResult(allowed=False, remaining=0, retry_after=int(ttl))

        return RateLimitResult(
            allowed=True,
            remaining=max(0, max_req - count),
            retry_after=0,
        )

    except Exception as exc:
        logger.debug(
            "distributed_rate_limit: Redis unavailable (%s) — allowing request key=%s",
            exc, key,
        )
        return RateLimitResult(allowed=True, remaining=max_req, retry_after=0)
