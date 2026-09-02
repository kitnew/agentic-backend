import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

COMPONENT_PUBLISHED_EVENT_TYPE: Literal["configuration.component.published.v1"] = (
    "configuration.component.published.v1"
)
COMPONENT_PUBLISHED_SUBJECT: Literal["evt.configuration.component.published.v1"] = (
    "evt.configuration.component.published.v1"
)
MANAGED_RESOURCE_CHANGED_EVENT_TYPE: Literal[
    "control_plane.managed_resource.changed.v1"
] = "control_plane.managed_resource.changed.v1"
MANAGED_RESOURCE_CHANGED_SUBJECT: Literal[
    "evt.control_plane.managed_resource.changed.v1"
] = "evt.control_plane.managed_resource.changed.v1"


class IntegrationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ComponentScope(IntegrationContract):
    type: Literal["platform", "tenant", "profile"]
    key: str | None


class ConfigurationComponentPublishedPayloadV1(IntegrationContract):
    component_id: UUID
    component_kind: str
    component_scope: ComponentScope
    revision_id: UUID
    revision_number: int
    schema_version: int
    previous_active_revision_id: UUID | None
    restored_from_revision_id: UUID | None


class ConfigurationComponentPublishedV1(IntegrationContract):
    event_id: UUID
    event_type: Literal["configuration.component.published.v1"] = (
        COMPONENT_PUBLISHED_EVENT_TYPE
    )
    schema_version: Literal[1] = 1
    occurred_at: datetime
    payload: ConfigurationComponentPublishedPayloadV1

    def to_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        ).encode()


class ManagedResourceChangedPayloadV1(IntegrationContract):
    resource_type: Literal["credential", "provider_connection", "model_deployment", "integration_connection"]
    resource_id: UUID
    action: Literal["created", "updated", "enabled", "disabled", "rotated", "revoked"]
    resource_generation: int
    status: str | None = None


class ManagedResourceChangedV1(IntegrationContract):
    event_id: UUID
    event_type: Literal["control_plane.managed_resource.changed.v1"] = (
        MANAGED_RESOURCE_CHANGED_EVENT_TYPE
    )
    schema_version: Literal[1] = 1
    occurred_at: datetime
    payload: ManagedResourceChangedPayloadV1

    def to_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        ).encode()
