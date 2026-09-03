import base64
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialCipher:
    ALGORITHM = "aes-256-gcm-v1"

    def __init__(self, encoded_key: str, key_id: str = "bootstrap") -> None:
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except ValueError as error:
            raise ValueError("CONTROL_PLANE_ENCRYPTION_KEY must be base64") from error
        if len(key) != 32:
            raise ValueError("CONTROL_PLANE_ENCRYPTION_KEY must contain 32 bytes")
        self._cipher = AESGCM(key)
        self.key_id = key_id

    def encrypt(
        self, credential_id: UUID, version_number: int, secret: str
    ) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return nonce, self._cipher.encrypt(
            nonce, secret.encode(), self._aad(credential_id, version_number)
        )

    def decrypt(
        self,
        credential_id: UUID,
        version_number: int,
        nonce: bytes,
        ciphertext: bytes,
        key_id: str,
        algorithm: str,
    ) -> str:
        if key_id != self.key_id or algorithm != self.ALGORITHM:
            raise ValueError("credential secret envelope is not supported")
        try:
            plaintext = self._cipher.decrypt(
                nonce, ciphertext, self._aad(credential_id, version_number)
            )
        except (InvalidTag, ValueError) as error:
            raise ValueError("credential secret could not be decrypted") from error
        return plaintext.decode()

    @staticmethod
    def _aad(credential_id: UUID, version_number: int) -> bytes:
        return f"control-plane-credential:{credential_id}:{version_number}".encode()
