import base64
from uuid import uuid4

import pytest
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.managed_resources import DeploymentKind, LLMCapabilities
from control_plane.domain.providers import default_provider_registry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponentRevision,
    OutboxMessage,
    ProviderConnection,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from sqlalchemy import func, select


def services(database: Database) -> tuple[ComponentService, ManagedResourceService]:
    registry = ComponentRegistry()
    register_runtime_components(registry)
    resources = ManagedResourceService(
        default_provider_registry(),
        SqlAlchemyManagedResourceRepository(
            database.sessions,
            CredentialCipher(base64.b64encode(b"0" * 32).decode()),
        ),
    )
    return ComponentService(registry, SqlAlchemyComponentRepository(database.sessions)), resources


async def deployment(
    resources: ManagedResourceService,
    kind: DeploymentKind,
    key: str,
    capabilities: LLMCapabilities | None = None,
):
    credential = await resources.create_credential(f"{key}-credential", "secret", "test")
    if kind is DeploymentKind.LLM:
        connection = await resources.create_connection(
            f"{key}-connection", "azure_openai", credential.ref,
            {"endpoint": "https://example.openai.azure.com"}, True, "test"
        )
        config = {"deployment_name": key, "model": key, "api_version": "2025-01-01-preview"}
    else:
        connection = await resources.create_connection(
            f"{key}-connection", "elevenlabs", credential.ref, {}, True, "test"
        )
        config = {"model_id": key}
    return await resources.create_deployment(
        key, connection.ref, kind, config, True, "test", capabilities
    )


def cascade_policy(strategy: str) -> dict[str, object]:
    stt_commit: dict[str, object] = {"strategy": strategy}
    if strategy == "provider_vad":
        stt_commit["provider_vad"] = {
            "threshold": 0.5, "silence_threshold_seconds": 0.35,
            "min_speech_ms": 100, "min_silence_ms": 350,
        }
    return {
        "speech_activity": {
            "min_speech_seconds": 0.05, "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "stt_commit": stt_commit,
        "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.7},
        "interruption": {
            "enabled": True, "min_duration_seconds": 0.5, "min_words": 0,
            "false_interruption_timeout_seconds": 2.0,
            "resume_after_false_interruption": True,
        },
        "response_scheduling": {
            "preemptive_generation": True, "preemptive_tts": True,
        },
    }


@pytest.mark.asyncio
async def test_runtime_publication_validates_resources_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(ComponentKind("runtime.llm.defaults"), PlatformScope())
    try:
        missing = uuid4()
        draft = await components.save_draft(
            address,
            {"deployment_ref": str(missing), "max_completion_tokens": 10},
            1, None, None, "test",
        )
        with pytest.raises(ManagedResourceNotFound):
            await components.publish_draft(address, draft.version, "test")
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 0

        terra = await deployment(
            resources, DeploymentKind.LLM, "terra-prod", LLMCapabilities(False, True)
        )
        draft = await components.save_draft(
            address,
            {"deployment_ref": str(terra.ref.value), "reasoning_effort": "high", "max_completion_tokens": 10},
            1, draft.version, None, "test",
        )
        revision = await components.publish_draft(address, draft.version, "test")
        assert revision.value.deployment_ref == terra.ref.value
        draft = await components.save_draft(
            address,
            {"deployment_ref": str(terra.ref.value), "temperature": 0.2, "max_completion_tokens": 10},
            1, None, revision.revision_id, "test",
        )
        with pytest.raises(InvalidComponentValue, match="temperature"):
            await components.publish_draft(address, draft.version, "test")
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_runtime_rollback_revalidates_current_deployment(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(ComponentKind("runtime.llm.defaults"), PlatformScope())
    try:
        terra = await deployment(
            resources, DeploymentKind.LLM, "rollback-terra", LLMCapabilities(False, True)
        )
        first_draft = await components.save_draft(
            address,
            {"deployment_ref": str(terra.ref.value), "reasoning_effort": "high", "max_completion_tokens": 10},
            1, None, None, "test",
        )
        first = await components.publish_draft(address, first_draft.version, "test")
        updated = await resources.update_deployment(
            terra.ref, terra.connection_ref, terra.deployment_config, terra.generation,
            "test", LLMCapabilities(True, False),
        )
        second_draft = await components.save_draft(
            address,
            {"deployment_ref": str(updated.ref.value), "temperature": 0.2, "max_completion_tokens": 10},
            1, None, first.revision_id, "test",
        )
        second = await components.publish_draft(address, second_draft.version, "test")
        async with database.sessions() as session:
            revisions = await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision))
            events = await session.scalar(select(func.count()).select_from(OutboxMessage))
        with pytest.raises(InvalidComponentValue, match="reasoning_effort"):
            await components.rollback(address, first.revision_number, "test")
        assert (await components.get_active(address)).revision_id == second.revision_id
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision)) == revisions
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == events
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_cascade_provider_vad_revalidates_current_stt_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    stt_address = ComponentAddress(ComponentKind("runtime.stt.defaults"), PlatformScope())
    cascade_address = ComponentAddress(
        ComponentKind("runtime.cascade.execution.defaults"), PlatformScope()
    )
    try:
        stt = await deployment(resources, DeploymentKind.STT, "cascade-scribe")
        stt_draft = await components.save_draft(
            stt_address, {"deployment_ref": str(stt.ref.value)},
            1, None, None, "test",
        )
        await components.publish_draft(stt_address, stt_draft.version, "test")
        provider_draft = await components.save_draft(
            cascade_address, cascade_policy("provider_vad"),
            1, None, None, "test",
        )
        provider_revision = await components.publish_draft(
            cascade_address, provider_draft.version, "test"
        )

        async with database.sessions.begin() as session:
            connection = await session.get(ProviderConnection, stt.connection_ref.value)
            assert connection is not None
            connection.provider_kind = "unsupported_stt"

        local_draft = await components.save_draft(
            cascade_address, cascade_policy("local_vad"),
            1, None, provider_revision.revision_id, "test",
        )
        local_revision = await components.publish_draft(
            cascade_address, local_draft.version, "test"
        )
        failed_draft = await components.save_draft(
            cascade_address, cascade_policy("provider_vad"),
            1, None, local_revision.revision_id, "test",
        )
        async with database.sessions() as session:
            revisions = await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision))
            events = await session.scalar(select(func.count()).select_from(OutboxMessage))

        with pytest.raises(InvalidComponentValue, match="does not support"):
            await components.publish_draft(cascade_address, failed_draft.version, "test")
        assert (await components.get_active(cascade_address)).revision_id == local_revision.revision_id
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision)) == revisions
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == events

        await components.discard_draft(cascade_address, failed_draft.version)
        with pytest.raises(InvalidComponentValue, match="does not support"):
            await components.rollback(cascade_address, provider_revision.revision_number, "test")
        assert (await components.get_active(cascade_address)).revision_id == local_revision.revision_id
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ConfigurationComponentRevision)) == revisions
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == events
    finally:
        await database.close()
