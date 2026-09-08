from __future__ import annotations

import base64

from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

OBSERVABILITY_FINGERPRINT_INFO = b"telephony-observability-fingerprint-v1"


def derive_observability_key(encoded_key: str) -> bytes:
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except ValueError as error:
        raise ValueError("INTEGRATION_ENCRYPTION_KEY must be base64") from error
    if len(key) != 32:
        raise ValueError("INTEGRATION_ENCRYPTION_KEY must contain 32 bytes")
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=OBSERVABILITY_FINGERPRINT_INFO,
    ).derive(key)
