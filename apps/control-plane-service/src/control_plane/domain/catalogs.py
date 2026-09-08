from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CatalogStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class Profile:
    key: str
    name: str
    description: str
    status: CatalogStatus
    generation: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InteractionMode:
    key: str
    name: str
    description: str
    status: CatalogStatus
    generation: int
    created_at: datetime
    updated_at: datetime
