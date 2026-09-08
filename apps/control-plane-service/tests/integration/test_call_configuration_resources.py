import asyncio

import pytest
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
)
from control_plane.domain.managed_resources import PhoneNumberAssignment
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponent,
    ConfigurationComponentRevision,
)
from sqlalchemy import func, select


def managed(database: Database) -> ManagedResourceService:
    return ManagedResourceService(
        SqlAlchemyManagedResourceRepository(database.sessions)
    )


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

        assert sum(isinstance(value, PhoneNumberAssignment) for value in did_race) == 1
        assert (
            sum(isinstance(value, ManagedResourceConflict) for value in did_race) == 1
        )
        assert all(isinstance(value, PhoneNumberAssignment) for value in tenant_race)
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
        assert (
            await service.create_phone_number_assignment(
                "tenant-a", "+421552301403", True, "bob"
            )
        ).enabled is True
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
        assert component_count == revision_count == 0
        assert not hasattr(replacement, "inbound_trunk_id")
    finally:
        await database.close()
