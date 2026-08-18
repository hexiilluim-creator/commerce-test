from __future__ import annotations

import json

import boto3

from .local_env import KMSProvider


class AWSSecretsManagerProvider(KMSProvider):
    def __init__(self, client=None) -> None:
        self.client = client or boto3.client("secretsmanager")

    async def get_secret(self, name: str) -> str:
        response = self.client.get_secret_value(SecretId=name)
        return response.get("SecretString") or json.dumps(response)
