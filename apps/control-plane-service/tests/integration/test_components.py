import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from control_plane.application.components import ComponentService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinition,
    ComponentDefinitionRegistry,
    ComponentDraft,
    ComponentKind,
    ComponentRevision,
    ComponentState,
    ScopeType,
    TenantScope,
)
from control_plane.domain.components.errors import (
    ActiveRevisionConflict,
    DraftVersionConflict,
    InvalidComponentValue,
    UnpublishedDraftConflict,
    UnsupportedSchemaVersion,
)
from control_plane.infrastructure.persistence.command_transactions import (
    component_command_scope,
)
from control_plane.infrastructure.persistence.database import (
    CONTROL_PLANE_SCHEMA_REVISION,
    Database,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


class ExampleSettings(BaseModel):
    enabled: bool
    label: str


def registry(schema_version: int = 1) -> ComponentDefinitionRegistry:
    result = ComponentDefinitionRegistry()
    result.register(
        ComponentDefinition(
            ComponentKind("example.settings"),
            ExampleSettings,
            frozenset({ScopeType.TENANT}),
            schema_version,
            metadata={"lifecycle": "versioned"},
        )
    )
    return result


def service(database: Database, schema_version: int = 1) -> ComponentService:
    return ComponentService(
        registry(schema_version),
        SqlAlchemyComponentRepository(database.sessions),
        component_command_scope(database.sessions),
    )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_concurrent_first_draft_creation_is_a_domain_conflict(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = service(database)
    address = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("concurrent-first-save")
    )
    try:
        results = await asyncio.gather(
            components.save_draft(
                address,
                {"enabled": True, "label": "a"},
                None,
                None,
                "alice",
            ),
            components.save_draft(
                address,
                {"enabled": False, "label": "b"},
                None,
                None,
                "bob",
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ComponentDraft) for result in results) == 1
        assert sum(isinstance(result, DraftVersionConflict) for result in results) == 1
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_components WHERE kind = 'example.settings' AND scope_type = 'tenant' AND scope_key = 'concurrent-first-save'"
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_drafts WHERE component_id = (SELECT id FROM control_plane.configuration_components WHERE kind = 'example.settings' AND scope_type = 'tenant' AND scope_key = 'concurrent-first-save')"
                    )
                )
                == 1
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_two_component_operations_share_caller_owned_transaction(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    first = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("transaction-first")
    )
    second = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("transaction-second")
    )
    try:
        async with database.sessions.begin() as session:
            components = ComponentService(
                registry(), SqlAlchemyComponentRepository(session)
            )
            first_draft = await components.save_draft(
                first, {"enabled": True, "label": "first"}, None, None, "operator"
            )
            await components.publish_draft(first, first_draft.version, "operator")
            second_draft = await components.save_draft(
                second, {"enabled": True, "label": "second"}, None, None, "operator"
            )
            await components.publish_draft(second, second_draft.version, "operator")

        async with database.sessions() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_revisions"
                    )
                )
                == 2
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_drafts"
                    )
                )
                == 0
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_failed_shared_transaction_rolls_back_all_component_changes(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    first = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("rollback-first")
    )
    second = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("rollback-second")
    )
    try:
        with pytest.raises(ActiveRevisionConflict):
            async with database.sessions.begin() as session:
                components = ComponentService(
                    registry(), SqlAlchemyComponentRepository(session)
                )
                draft = await components.save_draft(
                    first,
                    {"enabled": True, "label": "published"},
                    None,
                    None,
                    "operator",
                )
                await components.publish_draft(first, draft.version, "operator")
                await components.save_draft(
                    second,
                    {"enabled": True, "label": "must-roll-back"},
                    None,
                    uuid4(),
                    "operator",
                )

        async with database.sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM control_plane.configuration_components")
                )
                == 0
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_drafts"
                    )
                )
                == 0
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_revisions"
                    )
                )
                == 0
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_lifecycle_concurrency_and_http(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    components = service(database)
    address = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("tenant-a")
    )
    value = {"enabled": True, "label": "one"}
    try:
        draft = await components.save_draft(address, value, None, None, "alice")
        assert draft.version == 1 and draft.based_on_revision_id is None
        with pytest.raises(DraftVersionConflict):
            await components.save_draft(address, value, 99, None, "alice")

        r1 = await components.publish_draft(address, 1, "alice")
        assert r1.revision_number == 1
        assert (await components.get_component(address)).draft is None
        assert (
            await components.get_component(address)
        ).state is ComponentState.PUBLISHED

        draft = await components.save_draft(
            address, {"enabled": False, "label": "two"}, None, r1.revision_id, "bob"
        )
        assert draft.based_on_revision_id == r1.revision_id
        draft = await components.save_draft(
            address, {"enabled": False, "label": "updated"}, 1, r1.revision_id, "bob"
        )
        assert draft.version == 2
        assert (await components.get_active(address)).value == r1.value
        await components.discard_draft(address, 2)
        assert (await components.get_active(address)).revision_id == r1.revision_id
        assert len(await components.list_revisions(address)) == 1

        for label in ("two", "three"):
            active = await components.get_active(address)
            draft = await components.save_draft(
                address,
                {"enabled": False, "label": label},
                None,
                active.revision_id,
                "bob",
            )
            await components.publish_draft(address, draft.version, "bob")
        assert [
            item.revision_number for item in await components.list_revisions(address)
        ] == [
            3,
            2,
            1,
        ]
        assert (await components.get_revision(address, 1)).value == r1.value
        r4 = await components.rollback(address, 1, "carol")
        assert r4.revision_number == 4
        assert r4.value == r1.value
        assert (
            r4.based_on_revision_id
            == (await components.get_revision(address, 3)).revision_id
        )
        assert r4.restored_from_revision_id == r1.revision_id
        assert (await components.get_revision(address, 1)).value == r1.value
        assert len(await components.list_revisions(address)) == 4

        draft = await components.save_draft(
            address, value, None, r4.revision_id, "alice"
        )
        with pytest.raises(UnpublishedDraftConflict):
            await components.rollback(address, 1, "alice")
        await components.discard_draft(address, draft.version)
        with pytest.raises(UnsupportedSchemaVersion):
            await service(database, 2).rollback(address, 1, "alice")

        active = await components.get_active(address)
        draft = await components.save_draft(
            address, value, None, active.revision_id, "alice"
        )
        results = await asyncio.gather(
            components.publish_draft(address, draft.version, "alice"),
            components.publish_draft(address, draft.version, "alice"),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ComponentRevision) for result in results) == 1
        assert sum(isinstance(result, DraftVersionConflict) for result in results) == 1

        class Lifecycle:
            @asynccontextmanager
            async def lifespan(self, _app: Any):
                yield

        app = create_http_app(Lifecycle(), components)  # type: ignore[arg-type]
        app.state.settings = SimpleNamespace(
            control_plane_management_token=SimpleNamespace(
                get_secret_value=lambda: "management-secret"
            ),
            control_plane_management_actor="http",
            control_plane_management_scopes="configuration:read,configuration:write",
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-secret"},
        ) as client:
            base = "/management/v1/tenants/tenant-http/components/example.settings"
            response = await client.put(
                f"{base}/draft",
                headers={"If-Match": '"*"'},
                json={"value": value},
            )
            assert response.status_code == 200
            assert response.json()["draft"]["value"] == value
            assert (await client.get(f"{base}/draft")).status_code == 200
            etag = response.headers["etag"]
            response = await client.post(
                f"{base}/publish",
                headers={"If-Match": etag, "Idempotency-Key": "publish"},
            )
            assert response.status_code == 200
            assert response.json()["active"]["revision_number"] == 1
            assert (await client.get(f"{base}/active")).status_code == 200
            assert (await client.get(f"{base}/revisions/1")).status_code == 200
            assert (
                await client.put(
                    f"{base}/draft",
                    headers={"If-Match": '"stale"'},
                    json={"value": value},
                )
            ).status_code == 412
            etag = response.headers["etag"]
            assert (
                await client.put(
                    f"{base}/draft",
                    headers={"If-Match": etag},
                    json={"value": {"enabled": "bad", "label": "x"}},
                )
            ).status_code == 422
            response = await client.get(
                "/management/v1/tenants/tenant-a/components/example.settings/revisions"
            )
            assert response.status_code == 200 and len(response.json()) == 5
            response = await client.get(
                "/management/v1/tenants/tenant-a/components/missing"
            )
            assert response.status_code == 404

        invalid = ComponentAddress(
            ComponentKind("example.settings"), TenantScope("tenant-invalid")
        )
        await components.save_draft(invalid, value, None, None, "alice")
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "UPDATE control_plane.configuration_component_drafts SET value = '{\"enabled\": \"bad\"}'::jsonb WHERE component_id = (SELECT id FROM control_plane.configuration_components WHERE scope_key = 'tenant-invalid')"
                )
            )
        with pytest.raises(InvalidComponentValue):
            await components.publish_draft(invalid, 1, "alice")
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.configuration_component_drafts WHERE component_id = (SELECT id FROM control_plane.configuration_components WHERE scope_key = 'tenant-invalid')"
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT active_revision_id FROM control_plane.configuration_components WHERE scope_key = 'tenant-invalid'"
                    )
                )
                is None
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_migration_constraints_and_round_trip(
    isolated_database_url: str, alembic_config
) -> None:
    assert (
        ScriptDirectory.from_config(alembic_config).get_current_head()
        == CONTROL_PLANE_SCHEMA_REVISION
    )
    database = Database(isolated_database_url)
    async with database.sessions.begin() as session:
        await session.execute(
            text("CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY)")
        )
        await session.execute(
            text("INSERT INTO alembic_version VALUES ('backend_head')")
        )
    assert not await database.schema_compatible()
    await database.close()
    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    database = Database(isolated_database_url)
    try:
        assert await database.schema_compatible()
        async with database.sessions() as session:
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == "backend_head"
            )
            assert (
                await session.scalar(
                    text("SELECT to_regclass('control_plane.idempotency_replays')")
                )
                == "control_plane.idempotency_replays"
            )
            assert (
                await session.scalar(
                    text("SELECT to_regclass('control_plane.live_components')")
                )
                == "control_plane.live_components"
            )
            assert (
                await session.scalar(
                    text("SELECT to_regclass('control_plane.outbox_messages')")
                )
                is None
            )
        async with database.sessions.begin() as session:
            await session.execute(
                text("UPDATE control_plane_alembic_version SET version_num = 'stale'")
            )
        assert not await database.schema_compatible()
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "UPDATE control_plane_alembic_version SET version_num = :revision"
                ),
                {"revision": CONTROL_PLANE_SCHEMA_REVISION},
            )
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO control_plane.configuration_components (id, kind, scope_type, scope_key) VALUES (gen_random_uuid(), 'example.settings', 'platform', NULL)"
                )
            )
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "INSERT INTO control_plane.configuration_components (id, kind, scope_type, scope_key) VALUES (gen_random_uuid(), 'example.settings', 'platform', NULL)"
                    )
                )
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "INSERT INTO control_plane.configuration_components (id, kind, scope_type, scope_key) VALUES (gen_random_uuid(), 'bad.scope', 'tenant', NULL)"
                    )
                )
        components = service(database)
        first = ComponentAddress(
            ComponentKind("example.settings"), TenantScope("first")
        )
        second = ComponentAddress(
            ComponentKind("example.settings"), TenantScope("second")
        )
        first_revision = await components.publish_draft(
            first,
            (
                await components.save_draft(
                    first, {"enabled": True, "label": "first"}, None, None, "test"
                )
            ).version,
            "test",
        )
        await components.publish_draft(
            second,
            (
                await components.save_draft(
                    second, {"enabled": True, "label": "second"}, None, None, "test"
                )
            ).version,
            "test",
        )
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.configuration_components SET active_revision_id = :revision_id WHERE scope_key = 'second'"
                    ),
                    {"revision_id": first_revision.revision_id},
                )
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "INSERT INTO control_plane.configuration_component_revisions (id, component_id, revision_number, schema_version, value, created_by) SELECT gen_random_uuid(), id, 1, 1, '{}'::jsonb, 'test' FROM control_plane.configuration_components WHERE scope_key = 'first'"
                    )
                )
    finally:
        await database.close()
    await asyncio.to_thread(command.downgrade, alembic_config, "base")
    database = Database(isolated_database_url)
    assert not await database.schema_compatible()
    await database.close()
    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    database = Database(isolated_database_url)
    assert await database.schema_compatible()
    await database.close()
