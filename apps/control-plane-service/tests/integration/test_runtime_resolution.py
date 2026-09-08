from typing import cast

import pytest
from control_plane.application.components import ComponentService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.runtime_materialization import (
    ExecutionSnapshotService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    TenantScope,
)
from control_plane.domain.registries import ProviderKindRegistry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.domain.runtime_resolution import ResolvedCascadeRuntime
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)

from .test_system_configuration import desired, setup


def component_service(database: Database):
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    return ComponentService(
        registry,
        cast(ComponentRepository, SqlAlchemyComponentRepository(database.sessions)),
    )


@pytest.mark.asyncio
async def test_runtime_resolution_is_repeatable_read_and_read_only(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    reader = SqlAlchemyRuntimeResolutionReader(database.sessions)
    resolver = RuntimeResolver(
        registry,
        ProviderKindRegistry(),
        reader,
    )

    async def publish(kind: str, value: dict[str, object]):
        address = ComponentAddress(
            ComponentKind(kind),
            TenantScope("runtime-integration"),
        )
        draft = await components.save_draft(address, value, None, None, "test")
        return await components.publish_draft(address, draft.version, "test")

    try:
        first_configuration = desired(refs, voice="voice-a")
        applied = await system.apply(
            first_configuration, "*", "test", "runtime-system-a"
        )
        await publish(
            "runtime.architecture.policy", {"architectures": ["cascade"]}
        )
        await publish(
            "runtime.speech.overrides",
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": None},
            },
        )

        first = await resolver.resolve_runtime("runtime-integration")
        second_configuration = desired(refs, voice="voice-b")
        await system.apply(
            second_configuration,
            system.concurrency_token(applied.configuration),
            "test",
            "runtime-system-b",
        )
        second = await resolver.resolve_runtime("runtime-integration")

        assert isinstance(first.selected, ResolvedCascadeRuntime)
        assert first.selected.tts.voice == "voice-a"
        assert second.selected.tts.voice == "voice-b"
        assert first.selected.llm.component.component_kind == "LLMDefaults"
        assert first.selected.llm.component.revision_id is None
        loaded = await reader.load("runtime-integration")
        assert {str(address.kind) for address in loaded.live_components} == {
            "STTDefaults",
            "LLMDefaults",
            "TTSDefaults",
            "RealtimeDefaults",
            "Policies",
        }
        assert all(
            str(address.kind)
            not in {
                "runtime.llm.defaults",
                "runtime.stt.defaults",
                "runtime.tts.defaults",
                "runtime.cascade.execution.defaults",
                "runtime.realtime.execution.defaults",
            }
            for address in loaded.components
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_runtime_materialization_is_one_repeatable_read_write_transaction(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    reader = SqlAlchemyRuntimeResolutionReader(database.sessions)
    resolver = RuntimeResolver(registry, ProviderKindRegistry(), reader)
    materializer = ExecutionSnapshotService(
        database.sessions,
        resolver,
        reader,
        SqlAlchemyExecutionSnapshotRepository(database.sessions),
    )

    async def publish(kind: str, value: dict[str, object]):
        address = ComponentAddress(
            ComponentKind(kind),
            TenantScope("materialize"),
        )
        draft = await components.save_draft(address, value, None, None, "test")
        return await components.publish_draft(address, draft.version, "test")

    try:
        await system.apply(desired(refs), "*", "test", "materialize-system")
        await publish(
            "runtime.architecture.policy", {"architectures": ["cascade"]}
        )
        await publish(
            "runtime.speech.overrides",
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": None},
            },
        )
        first = await materializer.materialize_runtime("materialize")
        second = await materializer.materialize_runtime("materialize")
        assert first.snapshot_id != second.snapshot_id
        assert first.content_hash == second.content_hash
        assert await materializer.get_snapshot(first.snapshot_id) == first
        assert "ciphertext" not in str(first).lower()
    finally:
        await database.close()
