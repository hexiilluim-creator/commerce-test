"""services/ai_provider_manager.py — AI provider fallback manager.

Tracks provider availability and provides fallback stats for ops dashboards.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

ProviderName = Literal["openai", "deepseek", "anthropic", "gemini"]


@dataclass
class ProviderStats:
    name: str
    requests: int = 0
    failures: int = 0
    last_used: float | None = None
    last_failure: float | None = None

    @property
    def failure_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.failures / self.requests

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "requests": self.requests,
            "failures": self.failures,
            "failure_rate": round(self.failure_rate, 3),
            "last_used": self.last_used,
            "last_failure": self.last_failure,
        }


_provider_stats: dict[str, ProviderStats] = {
    name: ProviderStats(name=name) for name in ("openai", "deepseek", "anthropic", "gemini")
}


def record_request(provider: str, success: bool) -> None:
    stats = _provider_stats.setdefault(provider, ProviderStats(name=provider))
    stats.requests += 1
    stats.last_used = time.time()
    if not success:
        stats.failures += 1
        stats.last_failure = time.time()


async def get_fallback_stats() -> list[dict]:
    """Return current stats for all AI providers (used by ops dashboard)."""
    from services.circuit_breaker import _breakers

    result = []
    for name, stats in _provider_stats.items():
        entry = stats.to_dict()
        breaker = _breakers.get(name)
        entry["circuit_state"] = breaker.state if breaker else "closed"
        result.append(entry)
    return result
