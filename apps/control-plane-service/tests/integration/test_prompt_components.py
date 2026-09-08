import pytest
from control_plane.application.components import ComponentService
from control_plane.domain.catalogs import CatalogStatus
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import RevisionNotFound
from control_plane.domain.prompt_components import register_prompt_components
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.platform_catalogs import (
    SqlAlchemyPlatformRepository,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)


def service(database: Database) -> ComponentService:
    registry = ComponentDefinitionRegistry()
    register_prompt_components(registry)
    return ComponentService(
        registry,
        SqlAlchemyComponentRepository(database.sessions),  # type: ignore[arg-type]
    )


async def publish(service: ComponentService, address: ComponentAddress, content: str):
    active = None
    try:
        active = await service.get_active(address)
    except RevisionNotFound:
        pass
    draft = await service.save_draft(
        address,
        {"content": content},
        None,
        active.revision_id if active else None,
        "test",
    )
    return await service.publish_draft(address, draft.version, "test")


@pytest.mark.asyncio
async def test_prompt_addresses_are_independent_and_use_generic_lifecycle(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = service(database)
    async with database.sessions.begin() as session:
        catalogs = SqlAlchemyPlatformRepository(session)
        await catalogs.put_profile(
            "hotel", "Hotel", "Hotel profile", CatalogStatus.ENABLED, "test"
        )
        await catalogs.put_profile(
            "restaurant",
            "Restaurant",
            "Restaurant profile",
            CatalogStatus.ENABLED,
            "test",
        )
    system = ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope())
    hotel = ComponentAddress(ComponentKind("ProfilePrompt"), ProfileScope("hotel"))
    restaurant = ComponentAddress(
        ComponentKind("ProfilePrompt"), ProfileScope("restaurant")
    )
    tenant_a = ComponentAddress(ComponentKind("prompt.tenant"), TenantScope("a"))
    tenant_b = ComponentAddress(ComponentKind("prompt.tenant"), TenantScope("b"))
    try:
        await publish(components, system, "system")
        first_hotel = await publish(components, hotel, "hotel v1")
        await publish(components, restaurant, "restaurant")
        await publish(components, tenant_a, "tenant a")
        await publish(components, tenant_b, "tenant b")
        await publish(components, hotel, "hotel v2")
        restored = await components.rollback(hotel, 1, "test")

        assert restored.revision_number == 3
        assert (await components.get_active(system)).value.content == "system"
        assert (await components.get_active(hotel)).value.content == "hotel v1"
        assert (await components.get_active(restaurant)).value.content == "restaurant"
        assert (await components.get_active(tenant_a)).value.content == "tenant a"
        assert (await components.get_active(tenant_b)).value.content == "tenant b"
        assert first_hotel.revision_number == 1

        assert restored.restored_from_revision_id == first_hotel.revision_id
    finally:
        await database.close()
