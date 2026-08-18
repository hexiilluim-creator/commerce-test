"""services/circuit_breaker.py — Simple in-process circuit breaker for AI providers.

Tracks failure counts per provider and opens/closes circuits automatically.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds before trying again
    _failures: int = field(default=0, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self.recovery_timeout:
            return "half-open"
        return "open"

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning("circuit_breaker: %s OPENED after %s failures", self.name, self._failures)

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self._failures,
            "opened_at": self._opened_at,
        }


# Named breakers for known AI providers
openai_breaker = CircuitBreaker(name="openai", failure_threshold=5, recovery_timeout=60.0)
deepseek_breaker = CircuitBreaker(name="deepseek", failure_threshold=5, recovery_timeout=60.0)

_breakers: dict[str, CircuitBreaker] = {
    "openai": openai_breaker,
    "deepseek": deepseek_breaker,
}


def get_breaker(name: str) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def list_breakers() -> list[dict]:
    """Return stats for all registered circuit breakers."""
    return [b.stats() for b in _breakers.values()]
