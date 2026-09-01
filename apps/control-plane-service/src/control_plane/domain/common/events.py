from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
