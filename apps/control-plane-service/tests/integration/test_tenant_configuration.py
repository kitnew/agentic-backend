import asyncio

import pytest
from control_plane.application.tenant_configuration import (
    TenantConfigurationDesired,
    TenantConfigurationService,
)
from control_plane.domain.catalogs import CatalogStatus
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ProfileScope,
)
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.registries import ArchitectureRegistry
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponent,
    ConfigurationComponentDraft,
    ConfigurationComponentRevision,
    IdempotencyReplay,
    IntegrationConnection,
    LiveComponent,
    ProfileCatalogEntry,
)
from control_plane.infrastructure.persistence.platform_catalogs import (
    SqlAlchemyPlatformRepository,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.tenant_configuration_transactions import (
    tenant_configuration_command_scope,
)
from sqlalchemy import func, select


def desired(*, prompt="tenant"):
    return TenantConfigurationDesired.model_validate(
        {
            "tenant_prompt": {"content": prompt},
            "knowledge": {"content": "knowledge"},
            "agent_personality": {
                "identity": "concierge",
                "display_name": "Concierge",
                "greeting": "Welcome",
                "conversation_scope": "property_only",
            },
            "business_info": {
                "business": {"name": "Hotel", "type": "hotel"},
                "contact": {"phones": [], "emails": []},
                "localization": {
                    "default_locale": "en-US",
                    "timezone": "Europe/Bucharest",
                },
            },
            "actions_definition": {"actions": {}},
            "architecture": {"architecture_key": "cascade"},
            "profile_reference": {"profile_key": "sales"},
            "runtime_overrides": {"stt": {"keyterms": []}},
            "actions_availability": {"actions": {}},
        }
    )


def service(database):
    return TenantConfigurationService(
        default_component_definition_registry(),
        ArchitectureRegistry(),
        tenant_configuration_command_scope(database.sessions),
    )


async def seed_profile(database):
    registry = default_component_definition_registry()
    address = ComponentAddress(ComponentKind("ProfilePrompt"), ProfileScope("sales"))
    async with database.sessions.begin() as session:
        repository = SqlAlchemyPlatformRepository(session)
        await repository.put_profile(
            "sales", "Sales", "Sales profile", CatalogStatus.ENABLED, "alice"
        )
        definition = registry.resolve(address)
        draft = await repository.save_draft(
            address, {"content": "profile"}, 1, None, None, "alice"
        )
        await repository.publish_draft(address, draft.version, "alice", definition)


async def tenant_counts(database):
    async with database.sessions() as session:
        component_ids = select(ConfigurationComponent.id).where(
            ConfigurationComponent.scope_type == "tenant",
            ConfigurationComponent.scope_key == "tenant-a",
        )
        return (
            await session.scalar(
                select(func.count())
                .select_from(ConfigurationComponent)
                .where(ConfigurationComponent.id.in_(component_ids))
            ),
            await session.scalar(
                select(func.count())
                .select_from(ConfigurationComponentDraft)
                .where(ConfigurationComponentDraft.component_id.in_(component_ids))
            ),
            await session.scalar(
                select(func.count())
                .select_from(ConfigurationComponentRevision)
                .where(ConfigurationComponentRevision.component_id.in_(component_ids))
            ),
            await session.scalar(
                select(func.count())
                .select_from(LiveComponent)
                .where(
                    LiveComponent.scope_type == "tenant",
                    LiveComponent.scope_key == "tenant-a",
                )
            ),
            await session.scalar(select(func.count()).select_from(IdempotencyReplay)),
        )


async def tenant_rows(database):
    async with database.sessions() as session:
        rows = []
        for model in (
            ConfigurationComponent,
            ConfigurationComponentDraft,
            ConfigurationComponentRevision,
            LiveComponent,
            IdempotencyReplay,
            ProfileCatalogEntry,
            IntegrationConnection,
        ):
            for row in (await session.scalars(select(model))).all():
                rows.append(
                    tuple(
                        (column.name, getattr(row, column.name))
                        for column in model.__table__.columns
                    )
                )
        return tuple(rows)


@pytest.mark.asyncio
async def test_tenant_configuration_lock_is_scoped_per_tenant(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    scope = tenant_configuration_command_scope(database.sessions)

    async def hold(tenant_id, started, entered, release):
        started.set()
        async with scope(tenant_id):
            entered.set()
            await release.wait()

    first_started = asyncio.Event()
    first_entered = asyncio.Event()
    first_release = asyncio.Event()
    same_started = asyncio.Event()
    same_entered = asyncio.Event()
    same_release = asyncio.Event()
    other_started = asyncio.Event()
    other_entered = asyncio.Event()
    other_release = asyncio.Event()
    tasks = [
        asyncio.create_task(
            hold("tenant-a", first_started, first_entered, first_release)
        ),
    ]
    try:
        await asyncio.wait_for(first_entered.wait(), 1)
        tasks.append(
            asyncio.create_task(
                hold("tenant-a", same_started, same_entered, same_release)
            )
        )
        await asyncio.wait_for(same_started.wait(), 1)
        same_wait = asyncio.create_task(same_entered.wait())
        done, _ = await asyncio.wait({same_wait}, timeout=0.1)
        assert not done
        same_wait.cancel()

        tasks.append(
            asyncio.create_task(
                hold("tenant-b", other_started, other_entered, other_release)
            )
        )
        await asyncio.wait_for(other_started.wait(), 1)
        await asyncio.wait_for(other_entered.wait(), 1)
        other_release.set()
        await tasks[-1]

        first_release.set()
        await tasks[0]
        await asyncio.wait_for(same_entered.wait(), 1)
        same_release.set()
        await tasks[1]
    finally:
        first_release.set()
        same_release.set()
        other_release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await database.close()


@pytest.mark.asyncio
async def test_postgresql_plan_changes_no_rows_or_metadata(migrated_database_url):
    database = Database(migrated_database_url)
    try:
        await seed_profile(database)
        tenant = service(database)
        before = await tenant_rows(database)
        plan = await tenant.plan("tenant-a", desired())
        assert plan.valid
        assert await tenant_rows(database) == before

        applied = await tenant.apply("tenant-a", desired(), "*", "alice", "apply")
        before = await tenant_rows(database)
        no_op = await tenant.plan("tenant-a", desired())
        assert no_op.changes.immediate == no_op.changes.draft == ()
        assert await tenant_rows(database) == before
        assert applied.configuration.status.has_drafts
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_postgresql_mixed_apply_and_replay_failure_are_atomic(
    migrated_database_url, monkeypatch
):
    database = Database(migrated_database_url)
    await seed_profile(database)
    tenant = service(database)
    original = SqlAlchemyComponentRepository.save_draft

    async def fail_last(self, address, *args, **kwargs):
        if str(address.kind) == "ActionsDefinition":
            raise RuntimeError("last draft failed")
        return await original(self, address, *args, **kwargs)

    monkeypatch.setattr(SqlAlchemyComponentRepository, "save_draft", fail_last)
    try:
        with pytest.raises(RuntimeError, match="last draft"):
            await tenant.apply("tenant-a", desired(), "*", "alice", "failed")
        assert await tenant_counts(database) == (0, 0, 0, 0, 0)
    finally:
        monkeypatch.setattr(SqlAlchemyComponentRepository, "save_draft", original)

    original_add = SqlAlchemyIdempotencyRepository.add

    async def fail_replay(*_args, **_kwargs):
        raise RuntimeError("replay failed")

    monkeypatch.setattr(SqlAlchemyIdempotencyRepository, "add", fail_replay)
    try:
        with pytest.raises(RuntimeError, match="replay failed"):
            await tenant.apply("tenant-a", desired(), "*", "alice", "replay-failed")
        assert await tenant_counts(database) == (0, 0, 0, 0, 0)
    finally:
        monkeypatch.setattr(SqlAlchemyIdempotencyRepository, "add", original_add)
        await database.close()


@pytest.mark.asyncio
async def test_postgresql_multi_component_publish_is_atomic(
    migrated_database_url, monkeypatch
):
    database = Database(migrated_database_url)
    try:
        await seed_profile(database)
        tenant = service(database)
        applied = await tenant.apply("tenant-a", desired(), "*", "alice", "apply")
        original = SqlAlchemyComponentRepository.publish_draft

        async def fail_last(self, address, *args, **kwargs):
            if str(address.kind) == "ActionsDefinition":
                raise RuntimeError("last publish failed")
            return await original(self, address, *args, **kwargs)

        monkeypatch.setattr(SqlAlchemyComponentRepository, "publish_draft", fail_last)
        with pytest.raises(RuntimeError, match="last publish"):
            await tenant.publish(
                "tenant-a",
                tenant.concurrency_token(applied.configuration),
                "alice",
                "failed",
            )
        assert await tenant_counts(database) == (5, 5, 0, 4, 1)

        monkeypatch.setattr(SqlAlchemyComponentRepository, "publish_draft", original)

        async def fail_replay(*_args, **_kwargs):
            raise RuntimeError("publish replay failed")

        monkeypatch.setattr(SqlAlchemyIdempotencyRepository, "add", fail_replay)
        with pytest.raises(RuntimeError, match="publish replay failed"):
            await tenant.publish(
                "tenant-a",
                tenant.concurrency_token(applied.configuration),
                "alice",
                "replay-failed",
            )
        assert await tenant_counts(database) == (5, 5, 0, 4, 1)
    finally:
        await database.close()
