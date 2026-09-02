import base64
from uuid import uuid4

import pytest
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.capabilities import register_capability_components
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    TenantScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.providers import default_provider_registry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)


def services(database: Database) -> tuple[ComponentService, ManagedResourceService]:
    registry = ComponentRegistry()
    register_capability_components(registry)
    return (
        ComponentService(registry, SqlAlchemyComponentRepository(database.sessions)),
        ManagedResourceService(default_provider_registry(), SqlAlchemyManagedResourceRepository(database.sessions, CredentialCipher(base64.b64encode(b"0" * 32).decode()))),
    )


def capability(connection_id: str) -> dict[str, object]:
    return {
        "capabilities": {
            "reservation.create": {
                "enabled": True,
                "description": "Create reservation",
                "announcement": "Creating it.",
                "agent_input_schema": {"type": "object", "additionalProperties": False, "properties": {"guest": {"type": "string"}}},
                "execution": {"integration_connection_ref": connection_id, "method": "POST", "path": "/reservations", "request": {"codec": "json", "mapping": {"guest": {"$expr": "request.guest"}}}, "response": {"codec": "none"}, "timeout_seconds": 10},
            }
        }
    }


@pytest.mark.asyncio
async def test_capability_publication_resolves_live_tenant_connection(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(ComponentKind("capabilities.tenant"), TenantScope("tenant-a"))
    try:
        draft = await components.save_draft(address, capability(str(uuid4())), 1, None, None, "test")
        with pytest.raises(ManagedResourceNotFound):
            await components.publish_draft(address, draft.version, "test")

        connection = await resources.create_integration_connection("tenant-a", "booking-api", {"endpoint": "https://api.example.com", "authentication": {"type": "none"}}, None, True, "test")
        draft = await components.save_draft(address, capability(str(connection.ref.value)), 1, draft.version, None, "test")
        revision = await components.publish_draft(address, draft.version, "test")
        assert revision.revision_number == 1

        disabled = await resources.set_integration_connection_enabled(connection.ref, False, connection.generation, "test")
        assert (await components.get_active(address)).revision_id == revision.revision_id
        with pytest.raises(InvalidComponentValue, match="not enabled HTTP"):
            await components.rollback(address, revision.revision_number, "test")
        assert (await resources.get_integration_connection(connection.ref)).generation == disabled.generation
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_credential_lifecycle_never_rewrites_capability_revision(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(
        ComponentKind("capabilities.tenant"), TenantScope("tenant-b")
    )
    try:
        credential = await resources.create_credential(
            "booking-api-key", "secret", "test"
        )
        connection = await resources.create_integration_connection(
            "tenant-b",
            "booking-api",
            {
                "endpoint": "https://api.example.com",
                "authentication": {
                    "type": "api_key_header",
                    "header_name": "X-Api-Key",
                },
            },
            credential.ref,
            True,
            "test",
        )
        draft = await components.save_draft(
            address, capability(str(connection.ref.value)), 1, None, None, "test"
        )
        revision = await components.publish_draft(address, draft.version, "test")
        await resources.rotate_credential(credential.ref, "rotated", "test")
        await resources.revoke_credential(credential.ref, "test")
        assert (await components.get_active(address)).revision_id == revision.revision_id
        assert (await resources.get_integration_connection(connection.ref)).generation == 1
    finally:
        await database.close()
