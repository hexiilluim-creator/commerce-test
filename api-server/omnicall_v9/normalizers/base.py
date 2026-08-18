"""Base interfaces for future channel normalizers."""

from __future__ import annotations

from typing import Protocol

from omnicall_v9.types.unified_message import UnifiedMessage


class ChannelNormalizer(Protocol):
    """Protocol for future channel-specific normalizers."""

    def normalize(self, payload: dict[str, object]) -> UnifiedMessage:
        ...
