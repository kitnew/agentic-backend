from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class IntegrationSecretCipher:
    """Local AES-GCM boundary; replace this class with a KMS adapter when needed."""

    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except ValueError as error:
            raise ValueError("INTEGRATION_ENCRYPTION_KEY must be base64") from error
        if len(key) != 32:
            raise ValueError("INTEGRATION_ENCRYPTION_KEY must contain 32 bytes")
        self._cipher = AESGCM(key)
        self._fingerprint_key = hashlib.sha256(
            b"integration-fingerprint:" + key
        ).digest()

    def encrypt(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        version: int,
        secret: dict[str, object],
    ) -> tuple[bytes, bytes, str]:
        encoded = json.dumps(secret, ensure_ascii=False, separators=(",", ":")).encode()
        nonce = os.urandom(12)
        return (
            nonce,
            self._cipher.encrypt(
                nonce, encoded, self._aad(tenant_id, integration_id, version)
            ),
            hmac.new(self._fingerprint_key, encoded, hashlib.sha256).hexdigest(),
        )

    def decrypt(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        version: int,
        nonce: bytes,
        ciphertext: bytes,
    ) -> dict[str, object]:
        try:
            value = json.loads(
                self._cipher.decrypt(
                    nonce, ciphertext, self._aad(tenant_id, integration_id, version)
                )
            )
        except (InvalidTag, ValueError, json.JSONDecodeError) as error:
            raise ValueError("integration secret could not be decrypted") from error
        if not isinstance(value, dict):
            raise TypeError("integration secret is invalid")
        return value

    @staticmethod
    def _aad(tenant_id: UUID, integration_id: UUID, version: int) -> bytes:
        return f"{tenant_id}:{integration_id}:{version}".encode()
