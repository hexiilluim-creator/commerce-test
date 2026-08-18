"""AutoCommerce enterprise Omnical benchmark mix.

Usage:
  python tests/load/omnical_mix.py --base-url http://localhost:8000 --duration 300
"""
from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass

import httpx


@dataclass
class Scenario:
    channel: str
    weight: float
    path: str
    payload: dict


SCENARIOS = [
    Scenario('whatsapp', 0.40, '/api/v1/whatsapp/webhook', {'entry': []}),
    Scenario('facebook', 0.35, '/api/v1/social/facebook/webhook', {'entry': []}),
    Scenario('instagram', 0.15, '/api/v1/social/instagram/webhook', {'entry': []}),
    Scenario('tiktok', 0.10, '/api/v1/social/tiktok/webhook', {'event': 'comment'}),
]


async def worker(base_url: str, deadline: float, stats: dict[str, list[float]]):
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        while time.monotonic() < deadline:
            pick = random.choices(SCENARIOS, weights=[s.weight for s in SCENARIOS], k=1)[0]
            started = time.monotonic()
            try:
                response = await client.post(pick.path, json=pick.payload)
                latency = time.monotonic() - started
                stats.setdefault(f'{pick.channel}_status_{response.status_code}', []).append(latency)
                stats.setdefault('all', []).append(latency)
            except Exception:
                stats.setdefault(f'{pick.channel}_errors', []).append(10.0)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--duration', type=int, default=300)
    parser.add_argument('--concurrency', type=int, default=20)
    args = parser.parse_args()

    deadline = time.monotonic() + args.duration
    stats: dict[str, list[float]] = {}
    await asyncio.gather(*(worker(args.base_url, deadline, stats) for _ in range(args.concurrency)))

    latencies = sorted(stats.get('all', []))
    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return latencies[idx]

    print({
        'requests': len(latencies),
        'p50': round(pct(0.50), 3),
        'p95': round(pct(0.95), 3),
        'p99': round(pct(0.99), 3),
        'scenario_keys': sorted(stats),
    })


if __name__ == '__main__':
    asyncio.run(main())
