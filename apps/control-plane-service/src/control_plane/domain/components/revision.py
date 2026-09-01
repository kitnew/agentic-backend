from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

from control_plane.domain.components.base import ConfigurationComponent


@dataclass(frozen=True, slots=True)
class ComponentRevision:
    id: UUID
    component: ConfigurationComponent
    version: int
    content: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
