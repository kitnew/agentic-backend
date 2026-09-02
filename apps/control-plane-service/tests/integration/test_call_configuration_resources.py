import asyncio
import base64

import pytest
from contracts import ConfigurationComponentPublishedV1, ManagedResourceChangedV1
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    TenantScope,
)
from control_plane.domain.knowledge_components import register_knowledge_components
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
)
from control_plane.domain.managed_resources import PhoneNumberAssignment
from control_plane.domain.providers import default_provider_registry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponent,
    ConfigurationComponentRevision,
    OutboxMessage,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from sqlalchemy import func, select

KEY = base64.b64encode(b"0" * 32).decode()


def managed(database: Database) -> ManagedResourceService:
    return ManagedResourceService(
        default_provider_registry(),
        SqlAlchemyManagedResourceRepository(database.sessions, CredentialCipher(KEY)),
    )


def components(database: Database) -> ComponentService:
    registry = ComponentRegistry()
    register_knowledge_components(registry)
    return ComponentService(registry, SqlAlchemyComponentRepository(database.sessions))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_knowledge_uses_the_generic_independent_revision_lifecycle(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = components(database)
    address = ComponentAddress(
        ComponentKind("knowledge.tenant"), TenantScope("tenant-a")
    )
    try:
        first = await service.save_draft(
            address, {"content": "# First\nŽ"}, 1, None, None, "alice"
        )
        revision_one = await service.publish_draft(address, first.version, "alice")
        second = await service.save_draft(
            address, {"content": "# Second"}, 1, None, revision_one.revision_id, "bob"
        )
        await service.publish_draft(address, second.version, "bob")
        restored = await service.rollback(address, 1, "carol")

        assert restored.revision_number == 3
        assert (await service.get_active(address)).value.content == "# First\nŽ"
        async with database.sessions() as session:
            events = (await session.scalars(select(OutboxMessage))).all()
        published = [
            ConfigurationComponentPublishedV1.model_validate(event.payload)
            for event in events
        ]
        assert [event.payload.component_kind for event in published] == [
            "knowledge.tenant"
        ] * 3
        assert (
            published[-1].payload.restored_from_revision_id == revision_one.revision_id
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_phone_assignment_partial_unique_indexes_are_race_safe(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = managed(database)
    try:
        did_race = await asyncio.gather(
            service.create_phone_number_assignment(
                "tenant-c", "+421552301501", True, "alice"
            ),
            service.create_phone_number_assignment(
                "tenant-d", "+421552301501", True, "bob"
            ),
            return_exceptions=True,
        )
        tenant_race = await asyncio.gather(
            service.create_phone_number_assignment(
                "tenant-race", "+421552301502", True, "alice"
            ),
            service.create_phone_number_assignment(
                "tenant-race", "+421552301503", True, "bob"
            ),
            return_exceptions=True,
        )

        for results in (did_race, tenant_race):
            assert (
                sum(isinstance(value, PhoneNumberAssignment) for value in results) == 1
            )
            assert (
                sum(isinstance(value, ManagedResourceConflict) for value in results)
                == 1
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_handoff_and_phone_assignments_are_live_independent_cas_resources(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = managed(database)
    try:
        handoff = await service.create_handoff_destination(
            "tenant-a", "front_desk", "Front desk", "+421 552-301-299", True, "alice"
        )
        assert handoff.phone_number == "+421552301299"
        assert (
            await service.create_handoff_destination(
                "tenant-b", "front_desk", "Front desk", "+421552301300", False, "alice"
            )
        ).key == "front_desk"
        with pytest.raises(InvalidManagedResource):
            await service.create_handoff_destination(
                "tenant-a", "Bad-Key", "Front desk", "+421552301301", False, "alice"
            )
        with pytest.raises(ManagedResourceConflict):
            await service.create_handoff_destination(
                "tenant-a", "front_desk", "Duplicate", "+421552301302", False, "alice"
            )

        updated = await service.update_handoff_destination(
            handoff.ref, "Reception", "+421552301303", 1, "bob"
        )
        disabled = await service.set_handoff_destination_enabled(
            handoff.ref, False, 2, "bob"
        )
        assert (updated.generation, disabled.generation, disabled.enabled) == (
            2,
            3,
            False,
        )
        with pytest.raises(ManagedResourceConflict):
            await service.set_handoff_destination_enabled(handoff.ref, True, 2, "carol")
        assert [
            value.tenant_id
            for value in await service.list_handoff_destinations("tenant-a")
        ] == ["tenant-a"]
        assert not hasattr(disabled, "schedules")

        historical = await service.create_phone_number_assignment(
            "tenant-a", "+421 552 301 401", True, "alice"
        )
        historical = await service.set_phone_number_assignment_enabled(
            historical.ref, False, 1, "bob"
        )
        reassigned = await service.create_phone_number_assignment(
            "tenant-b", "+421552301401", True, "bob"
        )
        replacement = await service.create_phone_number_assignment(
            "tenant-a", "+421552301402", True, "bob"
        )
        assert historical.phone_number == reassigned.phone_number
        assert historical.enabled is False and reassigned.enabled is True
        assert (
            await service.get_phone_number_assignment(historical.ref)
        ).enabled is False
        with pytest.raises(ManagedResourceConflict):
            await service.create_phone_number_assignment(
                "tenant-c", "+421552301401", True, "bob"
            )
        with pytest.raises(ManagedResourceConflict):
            await service.create_phone_number_assignment(
                "tenant-a", "+421552301403", True, "bob"
            )
        with pytest.raises(ManagedResourceConflict):
            await service.set_phone_number_assignment_enabled(
                historical.ref, False, 1, "bob"
            )

        async with database.sessions() as session:
            component_count = await session.scalar(
                select(func.count()).select_from(ConfigurationComponent)
            )
            revision_count = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
            events = (
                await session.scalars(
                    select(OutboxMessage).order_by(OutboxMessage.created_at)
                )
            ).all()
        assert component_count == revision_count == 0
        changes = [
            ManagedResourceChangedV1.model_validate(event.payload).payload
            for event in events
        ]
        assert [(event.resource_type, event.action) for event in changes] == [
            ("handoff_destination", "created"),
            ("handoff_destination", "created"),
            ("handoff_destination", "updated"),
            ("handoff_destination", "disabled"),
            ("phone_number_assignment", "created"),
            ("phone_number_assignment", "disabled"),
            ("phone_number_assignment", "created"),
            ("phone_number_assignment", "created"),
        ]
        assert not hasattr(replacement, "inbound_trunk_id")
    finally:
        await database.close()
