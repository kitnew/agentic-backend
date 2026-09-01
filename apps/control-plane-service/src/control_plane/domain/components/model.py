from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ComponentKind:
    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value.strip() != self.value:
            raise ValueError("component kind must be a non-empty canonical string")

    def __str__(self) -> str:
        return self.value


class ScopeType(StrEnum):
    PLATFORM = "platform"
    TENANT = "tenant"
    PROFILE = "profile"


@dataclass(frozen=True, slots=True)
class PlatformScope:
    type: ScopeType = ScopeType.PLATFORM
    key: None = None


@dataclass(frozen=True, slots=True)
class TenantScope:
    tenant_id: str
    type: ScopeType = ScopeType.TENANT

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")

    @property
    def key(self) -> str:
        return self.tenant_id


@dataclass(frozen=True, slots=True)
class ProfileScope:
    profile_key: str
    type: ScopeType = ScopeType.PROFILE

    def __post_init__(self) -> None:
        if not self.profile_key:
            raise ValueError("profile_key is required")

    @property
    def key(self) -> str:
        return self.profile_key


ComponentScope = PlatformScope | TenantScope | ProfileScope


@dataclass(frozen=True, slots=True)
class ComponentAddress:
    kind: ComponentKind
    scope: ComponentScope


@dataclass(frozen=True, slots=True)
class ComponentDraft[T]:
    address: ComponentAddress
    value: T
    schema_version: int
    version: int
    based_on_revision_id: UUID | None
    updated_at: datetime
    updated_by: str


@dataclass(frozen=True, slots=True)
class ComponentRevision[T]:
    revision_id: UUID
    address: ComponentAddress
    revision_number: int
    value: T
    schema_version: int
    based_on_revision_id: UUID | None
    restored_from_revision_id: UUID | None
    created_at: datetime
    created_by: str


class ComponentState(StrEnum):
    EMPTY = "EMPTY"
    DRAFT_ONLY = "DRAFT_ONLY"
    PUBLISHED = "PUBLISHED"
    MODIFIED = "MODIFIED"

    @classmethod
    def derive(cls, *, has_active: bool, has_draft: bool) -> ComponentState:
        return {
            (False, False): cls.EMPTY,
            (False, True): cls.DRAFT_ONLY,
            (True, False): cls.PUBLISHED,
            (True, True): cls.MODIFIED,
        }[has_active, has_draft]


@dataclass(frozen=True, slots=True)
class ComponentSnapshot[T]:
    address: ComponentAddress
    state: ComponentState
    active: ComponentRevision[T] | None
    draft: ComponentDraft[T] | None
