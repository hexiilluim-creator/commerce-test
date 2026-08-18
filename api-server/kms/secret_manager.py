from __future__ import annotations

from .local_env import KMSProvider


class GoogleSecretManagerProvider(KMSProvider):
    def __init__(self, client=None) -> None:
        self.client = client

    async def get_secret(self, name: str) -> str:
        if self.client is None:
            raise RuntimeError("Google Secret Manager client not configured")
        response = self.client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
