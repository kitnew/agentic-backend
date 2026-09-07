import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


class IdempotencyKeyReused(Exception):
    code = "idempotency_key_reused"


@dataclass(frozen=True, slots=True)
class StoredReplay:
    request_fingerprint: str
    logical_result: dict[str, Any]


class IdempotencyRepository(Protocol):
    async def get(
        self, principal: str, operation: str, idempotency_key: str
    ) -> StoredReplay | None: ...

    async def add(
        self,
        principal: str,
        operation: str,
        idempotency_key: str,
        fingerprint: str,
        logical_result: dict[str, Any],
    ) -> None: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def request_fingerprint(logical_request: object) -> str:
    return hashlib.sha256(_canonical_bytes(logical_request)).hexdigest()


def opaque_concurrency_token(semantic_state: object) -> str:
    return (
        base64.urlsafe_b64encode(
            hashlib.sha256(_canonical_bytes(semantic_state)).digest()
        )
        .rstrip(b"=")
        .decode()
    )
