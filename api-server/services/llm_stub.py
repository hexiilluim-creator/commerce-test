"""
services/llm_stub.py — deterministic LLM provider used in Plan E.

Why a stub? Because the devcontainer has NO outbound network access and
NO paid LLM key; integration tests must pass offline. This module exposes
the exact same surface (`generate_text`, `translate`, `score_seo`, …) as
the production providers so swapping in OpenAI/Anthropic later is a one-line
change in `LLM_PROVIDER`.

All outputs are deterministic given the input text and a fixed seed, so
tests are reproducible without RNG flakiness.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

__production_blocker__ = "llm_stub is dev/test only"
if os.getenv("ENV", "development").strip().lower() in {"production", "prod", "staging"}:
    raise RuntimeError(__production_blocker__)


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "stub"          # stub | openai | anthropic
    seed: str = "autocommerce-v25"  # stable entropy source
    model: str = "stub-1"           # informational; tests assert 'stub'


def _seeded_text(prompt: str, length: int, cfg: LLMConfig) -> str:
    """Hash-derived pseudo-random text — deterministic, non-empty."""
    h = hashlib.sha256(f"{cfg.seed}:{prompt}".encode()).hexdigest()
    words = ("lorem ipsum dolor sit amet consectetur adipiscing elit "
             "sed do eiusmod tempor incididunt ut labore et dolore magna "
             "aliqua ut enim ad minim veniam quis nostrud").split()
    out: list[str] = []
    cursor = 0
    while sum(len(w) + 1 for w in out) < length:
        token = words[int(h[cursor % len(h)], 16) * len(words) // 256]
        cursor += 1
        out.append(token)
        if cursor > 4096:  # safety belt
            break
    return " ".join(out).capitalize() + "."


def generate_text(
    prompt: str,
    *,
    max_chars: int = 280,
    temperature: float = 0.0,
    cfg: LLMConfig | None = None,
) -> str:
    cfg = cfg or LLMConfig()
    text = _seeded_text(prompt, max_chars, cfg)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "."
    return text


def generate_bullets(prompt: str, n: int = 4) -> list[str]:
    LLMConfig()
    h = hashlib.sha256(f"bullets:{prompt}".encode()).hexdigest()
    words = ("premium", "durable", "eco", "rapide", "élégant", "compact",
             "léger", "fiable", "moderne", "polyvalent", "sécurisé", "éco-conçu")
    return [words[int(h[i], 16) * len(words) // 256].capitalize() for i in range(n)]


def seo_score(title: str, meta: str, keywords: Iterable[str]) -> int:
    """Cheap heuristic score 0-100; good enough to drive the SERP preview UX."""
    if not title or not meta:
        return 0
    score = 0
    if 30 <= len(title) <= 70:
        score += 30
    elif 10 <= len(title):
        score += 15
    if 80 <= len(meta) <= 180:
        score += 30
    elif 40 <= len(meta):
        score += 15
    kws = [k.lower() for k in keywords if k]
    if kws:
        cover = sum(1 for k in kws if k in title.lower()) + sum(1 for k in kws if k in meta.lower())
        score += min(40, cover * 10)
    return min(100, score)


def translate(text: str, target_locale: str, glossary: dict | None = None) -> str:
    """Pseudotranslation: prefix locale tag + keep glossary terms verbatim.
    This is enough to drive the diff view in the UI without a paid provider.
    """
    glossary = glossary or {}
    out = text
    for src, dst in glossary.items():
        out = re.sub(rf"\b{re.escape(src)}\b", dst, out, flags=re.IGNORECASE)
    return f"[{target_locale}] {out}"


CFG = LLMConfig()
