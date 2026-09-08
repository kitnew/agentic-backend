import pytest
from control_plane.application.command_support import IdempotencyKeyReused
from control_plane.application.components import ComponentService
from control_plane.application.platform_catalogs import (
    InteractionModeCreate,
    PlatformCatalogService,
    ProfileCreate,
    ProfileUpdate,
)
from control_plane.application.platform_configuration import (
    PlatformConfigurationDesired,
    PlatformConfigurationPreconditionFailed,
    PlatformConfigurationService,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    InteractionModeScope,
    ProfileScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.infrastructure.persistence.command_transactions import (
    component_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponent,
    ConfigurationComponentDraft,
    ConfigurationComponentRevision,
    IdempotencyReplay,
    InteractionModeCatalogEntry,
    ProfileCatalogEntry,
)
from control_plane.infrastructure.persistence.platform_configuration_transactions import (
    platform_configuration_command_scope,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError


def desired(*, profile_name="Sales", system="system"):
    return PlatformConfigurationDesired.model_validate(
        {
            "system_prompt": {"content": system},
            "profiles": [
                {
                    "key": "sales",
                    "name": profile_name,
                    "description": "Sales profile",
                    "status": "enabled",
                    "prompt": {"content": "profile"},
                }
            ],
            "interaction_modes": [
                {
                    "key": "voice",
                    "name": "Voice",
                    "description": "Voice mode",
                    "status": "enabled",
                    "prompt": {"content": "interaction"},
                }
            ],
        }
    )


def multi_desired():
    payload = desired().model_dump(mode="json")
    payload["profiles"].append(
        {
            "key": "support",
            "name": "Support",
            "description": "Support profile",
            "status": "enabled",
            "prompt": {"content": "support"},
        }
    )
    return PlatformConfigurationDesired.model_validate(payload)


def service(database):
    return PlatformConfigurationService(
        default_component_definition_registry(),
        platform_configuration_command_scope(database.sessions),
    )


def catalogs(database):
    return PlatformCatalogService(
        platform_configuration_command_scope(database.sessions)
    )


async def counts(database):
    async with database.sessions() as session:
        values = []
        for model in (
            ProfileCatalogEntry,
            InteractionModeCatalogEntry,
            ConfigurationComponent,
            ConfigurationComponentDraft,
            ConfigurationComponentRevision,
            IdempotencyReplay,
        ):
            values.append(await session.scalar(select(func.count()).select_from(model)))
        return tuple(values)


async def rows(database):
    async with database.sessions() as session:
        values = []
        for model in (
            ProfileCatalogEntry,
            InteractionModeCatalogEntry,
            ConfigurationComponent,
            ConfigurationComponentDraft,
            ConfigurationComponentRevision,
        ):
            for row in (await session.execute(select(model))).scalars().all():
                values.append(
                    tuple(
                        (column.name, getattr(row, column.name))
                        for column in model.__table__.columns
                    )
                )
        return tuple(values)


@pytest.mark.asyncio
async def test_plan_is_database_read_only_for_initial_and_existing_state(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    platform = service(database)
    try:
        before = await counts(database)
        first_plan = await platform.plan(desired())
        assert first_plan.valid and len(first_plan.catalog_changes) == 2
        assert await counts(database) == before == (0, 0, 0, 0, 0, 0)

        applied = await platform.apply(desired(), "*", "alice", "apply")
        before_rows = await rows(database)
        before_counts = await counts(database)
        no_op = await platform.plan(desired())
        assert no_op.valid and no_op.catalog_changes == no_op.draft_changes == ()
        after_rows = await rows(database)
        assert after_rows == before_rows
        assert await counts(database) == before_counts
        assert applied.configuration.status.has_drafts
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_apply_then_publish_separates_catalog_liveness_from_prompt_history(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    platform = service(database)
    try:
        applied = await platform.apply(desired(), "*", "alice", "apply")
        assert await counts(database) == (1, 1, 3, 3, 0, 1)
        assert applied.configuration.profiles[0].name == "Sales"
        assert applied.configuration.profiles[0].prompt.active is None

        published = await platform.publish(
            platform.concurrency_token(applied.configuration), "alice", "publish"
        )
        assert len(published.published_components) == 3
        assert await counts(database) == (1, 1, 3, 0, 3, 2)
        assert published.configuration.system_prompt.active.content == "system"

        metadata = await platform.apply(
            desired(profile_name="Revenue"),
            platform.concurrency_token(published.configuration),
            "alice",
            "metadata",
        )
        assert metadata.configuration.profiles[0].name == "Revenue"
        assert await counts(database) == (1, 1, 3, 0, 3, 3)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_mixed_apply_and_multi_prompt_publish_are_atomic(
    migrated_database_url, monkeypatch
):
    database = Database(migrated_database_url)
    platform = service(database)
    original_save = SqlAlchemyComponentRepository.save_draft

    async def fail_last_save(self, address, *args, **kwargs):
        if str(address.kind) == "InteractionPrompt":
            raise RuntimeError("last draft failed")
        return await original_save(self, address, *args, **kwargs)

    monkeypatch.setattr(SqlAlchemyComponentRepository, "save_draft", fail_last_save)
    try:
        with pytest.raises(RuntimeError, match="last draft"):
            await platform.apply(multi_desired(), "*", "alice", "failed-apply")
        assert await counts(database) == (0, 0, 0, 0, 0, 0)
    finally:
        monkeypatch.setattr(SqlAlchemyComponentRepository, "save_draft", original_save)

    try:
        applied = await platform.apply(multi_desired(), "*", "alice", "apply")
        original_publish = SqlAlchemyComponentRepository.publish_draft

        async def fail_last_publish(self, address, *args, **kwargs):
            if str(address.kind) == "InteractionPrompt":
                raise RuntimeError("last publish failed")
            return await original_publish(self, address, *args, **kwargs)

        monkeypatch.setattr(
            SqlAlchemyComponentRepository, "publish_draft", fail_last_publish
        )
        with pytest.raises(RuntimeError, match="last publish"):
            await platform.publish(
                platform.concurrency_token(applied.configuration),
                "alice",
                "failed-publish",
            )
        assert await counts(database) == (2, 1, 4, 4, 0, 1)
        monkeypatch.setattr(
            SqlAlchemyComponentRepository, "publish_draft", original_publish
        )
        published = await platform.publish(
            platform.concurrency_token(applied.configuration),
            "alice",
            "publish",
        )
        assert len(published.published_components) == 4
        assert await counts(database) == (2, 1, 4, 0, 4, 2)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_apply_idempotency_replay_and_replay_failure_rollback(
    migrated_database_url, monkeypatch
):
    database = Database(migrated_database_url)
    platform = service(database)
    try:
        first = await platform.apply(desired(), "*", "alice", "same")
        assert await platform.apply(desired(), "*", "alice", "same") == first
        with pytest.raises(IdempotencyKeyReused):
            await platform.apply(desired(system="changed"), "*", "alice", "same")
        with pytest.raises(PlatformConfigurationPreconditionFailed):
            await platform.apply(desired(system="changed"), "stale", "alice", "stale")
    finally:
        await database.close()

    database = Database(migrated_database_url)
    platform = service(database)

    async def fail_replay(*_args, **_kwargs):
        raise RuntimeError("replay write failed")

    monkeypatch.setattr(SqlAlchemyIdempotencyRepository, "add", fail_replay)
    try:
        current = await platform.get()
        with pytest.raises(RuntimeError, match="replay write failed"):
            await platform.apply(
                desired(profile_name="Retry"),
                platform.concurrency_token(current),
                "alice",
                "replay-failure",
            )
        assert (await platform.get()).profiles[0].name == "Sales"
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "scope", "message"),
    [
        ("ProfilePrompt", ProfileScope("missing"), "profile catalog"),
        (
            "InteractionPrompt",
            InteractionModeScope("missing"),
            "interaction mode catalog",
        ),
    ],
)
async def test_low_level_scoped_prompt_requires_catalog_entry(
    migrated_database_url, kind, scope, message
):
    database = Database(migrated_database_url)
    repository = SqlAlchemyComponentRepository(database.sessions)
    try:
        with pytest.raises(InvalidComponentValue, match=message):
            await repository.save_draft(
                ComponentAddress(ComponentKind(kind), scope),
                {"content": "profile"},
                1,
                None,
                None,
                "alice",
            )
        assert await counts(database) == (0, 0, 0, 0, 0, 0)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_catalogs_persist_current_state_without_prompt_history(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    catalog = catalogs(database)
    try:
        profile = await catalog.create_profile(
            ProfileCreate(key="sales", name="Sales", description="Sell"),
            "alice",
            "profile",
        )
        mode = await catalog.create_interaction_mode(
            InteractionModeCreate(key="voice", name="Voice", description="Calls"),
            "alice",
            "mode",
        )
        updated = await catalog.update_profile(
            "sales",
            ProfileUpdate(name="Revenue", description="Sell more"),
            catalog.concurrency_token(profile),
            "alice",
            "profile-update",
        )
        assert updated.key == "sales" and mode.key == "voice"
        assert await counts(database) == (1, 1, 0, 0, 0, 3)
        with pytest.raises(DBAPIError, match="catalog key is immutable"):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.profile_catalog SET key = 'renamed' WHERE key = 'sales'"
                    )
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_publish_replay_failure_rolls_back_all_revisions(
    migrated_database_url, monkeypatch
):
    database = Database(migrated_database_url)
    platform = service(database)
    try:
        applied = await platform.apply(desired(), "*", "alice", "apply")

        async def fail_replay(*_args, **_kwargs):
            raise RuntimeError("publish replay failed")

        monkeypatch.setattr(SqlAlchemyIdempotencyRepository, "add", fail_replay)
        with pytest.raises(RuntimeError, match="publish replay failed"):
            await platform.publish(
                platform.concurrency_token(applied.configuration),
                "alice",
                "publish",
            )
        assert await counts(database) == (1, 1, 3, 3, 0, 1)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_target_prompt_http_uses_value_only_write_and_etag(
    migrated_database_url,
):
    class Lifecycle:
        @asynccontextmanager
        async def lifespan(self, _app):
            yield

    database = Database(migrated_database_url)
    components = ComponentService(
        default_component_definition_registry(),
        SqlAlchemyComponentRepository(database.sessions),
        component_command_scope(database.sessions),
    )
    app = create_http_app(Lifecycle(), components=components)  # type: ignore[arg-type]
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "secret"
        ),
        control_plane_management_actor="alice",
        control_plane_management_scopes="configuration:read,configuration:write",
    )
    headers = {"Authorization": "Bearer secret", "If-Match": '"*"'}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.put(
                "/management/v1/platform/components/SystemPrompt/draft",
                headers=headers,
                json={"value": {"content": "system"}, "schema_version": 1},
            )
            saved = await client.put(
                "/management/v1/platform/components/SystemPrompt/draft",
                headers=headers,
                json={"value": {"content": "system"}},
            )
            published = await client.post(
                "/management/v1/platform/components/SystemPrompt/publish",
                headers={
                    **headers,
                    "If-Match": saved.headers["etag"],
                    "Idempotency-Key": "publish",
                },
            )
        assert invalid.status_code == 422
        assert saved.status_code == 200
        assert set(saved.json()["draft"]) == {
            "schema_version",
            "value",
            "based_on_revision_number",
            "updated_at",
            "updated_by",
        }
        assert published.status_code == 200
        assert published.json()["active"]["value"] == {"content": "system"}
    finally:
        await database.close()


from contextlib import asynccontextmanager
from types import SimpleNamespace
