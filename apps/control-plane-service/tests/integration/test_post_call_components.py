import base64
from typing import cast
from uuid import uuid4

import pytest
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    TenantScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.post_call import register_post_call_components
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
    register_post_call_components(registry)
    return (
        ComponentService(
            registry,
            cast(
                ComponentRepository,
                SqlAlchemyComponentRepository(database.sessions),
            ),
        ),
        ManagedResourceService(
            default_provider_registry(),
            SqlAlchemyManagedResourceRepository(
                database.sessions,
                CredentialCipher(base64.b64encode(b"0" * 32).decode()),
            ),
        ),
    )


def policy(connection_id: str) -> dict[str, object]:
    return {
        "actions": [
            {
                "action_id": "send_summary",
                "inputs": {
                    "summary": {
                        "artifact": "call_summary",
                        "representation": "plain_text",
                    }
                },
                "execution": {
                    "integration_connection_ref": connection_id,
                    "method": "POST",
                    "path": "/summaries",
                    "request": {
                        "codec": "json",
                        "mapping": {"summary": {"$expr": "inputs.summary.value"}},
                    },
                    "response": {"codec": "none"},
                    "timeout_seconds": 10,
                },
            }
        ]
    }


@pytest.mark.asyncio
async def test_post_call_draft_defers_live_connection_validation(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(
        ComponentKind("post_call.tenant"), TenantScope("tenant-a")
    )
    try:
        draft = await components.save_draft(
            address, policy(str(uuid4())), 1, None, None, "test"
        )
        with pytest.raises(ManagedResourceNotFound):
            await components.publish_draft(address, draft.version, "test")
        assert await components.list_revisions(address) == []

        foreign = await resources.create_integration_connection(
            "tenant-b",
            "foreign-api",
            {"endpoint": "https://api.example.com", "authentication": {"type": "none"}},
            None,
            True,
            "test",
        )
        draft = await components.save_draft(
            address, policy(str(foreign.ref.value)), 1, draft.version, None, "test"
        )
        with pytest.raises(InvalidComponentValue, match="another tenant"):
            await components.publish_draft(address, draft.version, "test")
        assert await components.list_revisions(address) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_post_call_publish_and_rollback_revalidate_live_http_connection(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(
        ComponentKind("post_call.tenant"), TenantScope("tenant-a")
    )
    try:
        connection = await resources.create_integration_connection(
            "tenant-a",
            "summary-api",
            {"endpoint": "https://api.example.com", "authentication": {"type": "none"}},
            None,
            True,
            "test",
        )
        draft = await components.save_draft(
            address, policy(str(connection.ref.value)), 1, None, None, "test"
        )
        revision = await components.publish_draft(address, draft.version, "test")
        updated = await resources.update_integration_connection(
            connection.ref,
            {"endpoint": "https://api.example.org", "authentication": {"type": "none"}},
            None,
            connection.generation,
            "test",
        )
        assert (
            await components.get_active(address)
        ).revision_id == revision.revision_id

        await resources.set_integration_connection_enabled(
            connection.ref, False, updated.generation, "test"
        )
        assert (
            await components.get_active(address)
        ).revision_id == revision.revision_id
        with pytest.raises(InvalidComponentValue, match="not enabled HTTP"):
            await components.rollback(address, revision.revision_number, "test")
        assert (
            await components.get_active(address)
        ).revision_id == revision.revision_id
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_post_call_credential_changes_never_rewrite_revision(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(
        ComponentKind("post_call.tenant"), TenantScope("tenant-a")
    )
    try:
        credential = await resources.create_credential("summary-api", "secret", "test")
        connection = await resources.create_integration_connection(
            "tenant-a",
            "summary-api",
            {
                "endpoint": "https://api.example.com",
                "authentication": {"type": "api_key_header", "header_name": "X-Key"},
            },
            credential.ref,
            True,
            "test",
        )
        draft = await components.save_draft(
            address, policy(str(connection.ref.value)), 1, None, None, "test"
        )
        revision = await components.publish_draft(address, draft.version, "test")
        assert "secret" not in str(revision.value.model_dump(mode="json"))
        await resources.rotate_credential(credential.ref, "rotated", "test")
        await resources.revoke_credential(credential.ref, "test")
        assert (
            await components.get_active(address)
        ).revision_id == revision.revision_id
        with pytest.raises(InvalidComponentValue, match="credential is not usable"):
            await components.rollback(address, revision.revision_number, "test")
    finally:
        await database.close()
