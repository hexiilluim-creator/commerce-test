from __future__ import annotations

import os


class KMSProvider:
    async def get_secret(self, name: str) -> str:
        raise NotImplementedError


class LocalEnvKMSProvider(KMSProvider):
    async def get_secret(self, name: str) -> str:
        return os.getenv(name, "")
