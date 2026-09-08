import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel

SNAPSHOT_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    snapshot_id: UUID
    schema_version: int
    tenant_id: str
    architecture: str
    created_at: datetime
    target: Mapping[str, object]
    content_hash: str

    @property
    def execution_id(self) -> UUID:
        return self.snapshot_id


def snapshot_payload(target: Mapping[str, object]) -> dict[str, object]:
    payload = _json_value(target)
    assert isinstance(payload, dict)
    return payload


def content_hash(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def assert_secret_free_payload(payload: Mapping[str, object]) -> None:
    forbidden = {
        "secret",
        "ciphertext",
        "nonce",
        "key_id",
        "algorithm",
        "active_version_id",
        "active_secret_version_number",
        "credential_version_id",
        "credential_version_number",
    }

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            leaked = forbidden.intersection(str(key).lower() for key in value)
            if leaked:
                raise ValueError(
                    f"execution snapshot contains secret material: {sorted(leaked)}"
                )
            for item in value.values():
                visit(item)
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)

    visit(payload)


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value
