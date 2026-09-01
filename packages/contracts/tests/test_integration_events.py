from datetime import UTC, datetime
from uuid import UUID

from contracts import (
    COMPONENT_PUBLISHED_EVENT_TYPE,
    COMPONENT_PUBLISHED_SUBJECT,
    MANAGED_RESOURCE_CHANGED_EVENT_TYPE,
    MANAGED_RESOURCE_CHANGED_SUBJECT,
    ComponentScope,
    ConfigurationComponentPublishedPayloadV1,
    ConfigurationComponentPublishedV1,
    ManagedResourceChangedPayloadV1,
    ManagedResourceChangedV1,
)


def test_component_published_contract_is_versioned_and_deterministic() -> None:
    event = ConfigurationComponentPublishedV1(
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        occurred_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        payload=ConfigurationComponentPublishedPayloadV1(
            component_id=UUID("00000000-0000-0000-0000-000000000002"),
            component_kind="example.settings",
            component_scope=ComponentScope(type="tenant", key="tenant-a"),
            revision_id=UUID("00000000-0000-0000-0000-000000000003"),
            revision_number=7,
            schema_version=1,
            previous_active_revision_id=None,
            restored_from_revision_id=None,
        ),
    )

    assert event.event_type == COMPONENT_PUBLISHED_EVENT_TYPE
    assert COMPONENT_PUBLISHED_SUBJECT == "evt.configuration.component.published.v1"
    assert event.schema_version == 1
    assert event.to_bytes() == event.to_bytes()
    assert (
        ConfigurationComponentPublishedV1.model_validate_json(event.to_bytes()) == event
    )


def test_managed_resource_changed_contract_is_secret_free() -> None:
    event = ManagedResourceChangedV1(
        event_id=UUID("00000000-0000-0000-0000-000000000004"),
        occurred_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        payload=ManagedResourceChangedPayloadV1(
            resource_type="credential",
            resource_id=UUID("00000000-0000-0000-0000-000000000005"),
            action="rotated",
            resource_generation=2,
            status="active",
        ),
    )

    assert event.event_type == MANAGED_RESOURCE_CHANGED_EVENT_TYPE
    assert (
        MANAGED_RESOURCE_CHANGED_SUBJECT
        == "evt.control_plane.managed_resource.changed.v1"
    )
    assert ManagedResourceChangedV1.model_validate_json(event.to_bytes()) == event
    assert b"secret" not in event.to_bytes().lower()
