import base64
from typing import cast

import pytest
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.runtime_materialization import (
    RuntimeMaterializationService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.managed_resources import (
    DeploymentKind,
    LLMCapabilities,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.domain.providers import default_provider_registry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.domain.runtime_resolution import ResolvedCascadeRuntime
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import OutboxMessage
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyRuntimeExecutionSnapshotRepository,
)
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)
from sqlalchemy import func, select


def services(database: Database):
    registry = ComponentRegistry()
    register_runtime_components(registry)
    return (
        ComponentService(
            registry,
            cast(ComponentRepository, SqlAlchemyComponentRepository(database.sessions)),
        ),
        ManagedResourceService(
            default_provider_registry(),
            SqlAlchemyManagedResourceRepository(
                database.sessions,
                CredentialCipher(base64.b64encode(b"0" * 32).decode()),
            ),
        ),
    )


async def deployment(
    resources: ManagedResourceService,
    kind: DeploymentKind,
    key: str,
    capabilities: LLMCapabilities | None = None,
):
    credential = await resources.create_credential(
        f"{key}-credential", "secret", "test"
    )
    provider = "azure_openai" if kind is DeploymentKind.LLM else "elevenlabs"
    connection = await resources.create_connection(
        f"{key}-connection",
        provider,
        credential.ref,
        {"endpoint": "https://example.openai.azure.com"}
        if provider == "azure_openai"
        else {},
        True,
        "test",
    )
    config = (
        {"deployment_name": key, "model": key, "api_version": "2026-01-01"}
        if kind is DeploymentKind.LLM
        else {"model_id": key}
    )
    return await resources.create_deployment(
        key,
        connection.ref,
        kind,
        config,
        True,
        "test",
        capabilities,
        RealtimeCapabilities(True, True) if kind is DeploymentKind.REALTIME else None,
        STTCapabilities(True, False) if kind is DeploymentKind.STT else None,
    )


def cascade_policy() -> dict[str, object]:
    return {
        "speech_activity": {
            "min_speech_seconds": 0.05,
            "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "stt_commit": {"strategy": "local_vad"},
        "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.7},
        "interruption": {
            "enabled": True,
            "min_duration_seconds": 0.5,
            "min_words": 0,
            "false_interruption_timeout_seconds": 2.0,
            "resume_after_false_interruption": True,
        },
        "response_scheduling": {
            "preemptive_generation": True,
            "preemptive_tts": True,
        },
    }


@pytest.mark.asyncio
async def test_runtime_resolution_is_repeatable_read_and_read_only(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    registry = ComponentRegistry()
    register_runtime_components(registry)
    resolver = RuntimeResolver(
        registry,
        default_provider_registry(),
        SqlAlchemyRuntimeResolutionReader(database.sessions),
    )

    async def publish(kind: str, value: dict[str, object], tenant: bool = False):
        address = ComponentAddress(
            ComponentKind(kind),
            TenantScope("runtime-integration") if tenant else PlatformScope(),
        )
        draft = await components.save_draft(address, value, 1, None, None, "test")
        return await components.publish_draft(address, draft.version, "test")

    try:
        llm = await deployment(
            resources,
            DeploymentKind.LLM,
            "resolver-llm",
            LLMCapabilities(True, True),
        )
        stt = await deployment(resources, DeploymentKind.STT, "resolver-stt")
        tts = await deployment(resources, DeploymentKind.TTS, "resolver-tts")
        await publish(
            "runtime.llm.defaults",
            {
                "deployment_ref": str(llm.ref.value),
                "max_completion_tokens": 1024,
            },
        )
        await publish("runtime.stt.defaults", {"deployment_ref": str(stt.ref.value)})
        await publish(
            "runtime.tts.defaults",
            {
                "deployment_ref": str(tts.ref.value),
                "default_voice_id": "voice-default",
                "min_sentence_chars": 20,
            },
        )
        await publish("runtime.cascade.execution.defaults", cascade_policy())
        await publish(
            "runtime.architecture.policy", {"architectures": ["cascade"]}, True
        )
        await publish(
            "runtime.speech.overrides",
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": None},
            },
            True,
        )

        async with database.sessions() as session:
            before = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        first = await resolver.resolve_runtime("runtime-integration")
        second = await resolver.resolve_runtime("runtime-integration")
        async with database.sessions() as session:
            after = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )

        assert first == second
        assert isinstance(first.selected, ResolvedCascadeRuntime)
        assert first.selected.llm.resource.deployment.generation == llm.generation
        assert first.selected.stt.resource.connection.generation == stt.generation
        assert await resources.get_deployment(llm.ref) == llm
        assert before == after
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_runtime_materialization_is_one_repeatable_read_write_transaction(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    registry = ComponentRegistry()
    register_runtime_components(registry)
    reader = SqlAlchemyRuntimeResolutionReader(database.sessions)
    resolver = RuntimeResolver(registry, default_provider_registry(), reader)
    materializer = RuntimeMaterializationService(
        database.sessions,
        resolver,
        reader,
        SqlAlchemyRuntimeExecutionSnapshotRepository(database.sessions),
    )

    async def publish(kind: str, value: dict[str, object], tenant: bool = False):
        address = ComponentAddress(
            ComponentKind(kind),
            TenantScope("materialize") if tenant else PlatformScope(),
        )
        draft = await components.save_draft(address, value, 1, None, None, "test")
        return await components.publish_draft(address, draft.version, "test")

    try:
        llm = await deployment(
            resources, DeploymentKind.LLM, "snapshot-llm", LLMCapabilities(True, True)
        )
        stt = await deployment(resources, DeploymentKind.STT, "snapshot-stt")
        tts = await deployment(resources, DeploymentKind.TTS, "snapshot-tts")
        await publish(
            "runtime.llm.defaults",
            {"deployment_ref": str(llm.ref.value), "max_completion_tokens": 1024},
        )
        await publish("runtime.stt.defaults", {"deployment_ref": str(stt.ref.value)})
        await publish(
            "runtime.tts.defaults",
            {
                "deployment_ref": str(tts.ref.value),
                "default_voice_id": "voice-default",
                "min_sentence_chars": 20,
            },
        )
        await publish("runtime.cascade.execution.defaults", cascade_policy())
        await publish(
            "runtime.architecture.policy", {"architectures": ["cascade"]}, True
        )
        await publish(
            "runtime.speech.overrides",
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": None},
            },
            True,
        )
        async with database.sessions() as session:
            before = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        first = await materializer.materialize_runtime("materialize")
        second = await materializer.materialize_runtime("materialize")
        assert first.snapshot_id != second.snapshot_id
        assert first.content_hash == second.content_hash
        assert await materializer.get_snapshot(first.snapshot_id) == first
        assert "ciphertext" not in str(first).lower()
        async with database.sessions() as session:
            after = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        assert before == after
    finally:
        await database.close()
