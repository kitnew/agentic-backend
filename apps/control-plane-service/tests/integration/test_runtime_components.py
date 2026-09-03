import base64
from uuid import uuid4

import pytest
from contracts import COMPONENT_PUBLISHED_EVENT_TYPE, ConfigurationComponentPublishedV1
from control_plane.application.components import ComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.managed_resources import (
    DeploymentKind,
    LLMCapabilities,
    RealtimeCapabilities,
    STTCapabilities,
)
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
    return ComponentService(
        registry, SqlAlchemyComponentRepository(database.sessions)
    ), resources


async def deployment(
    resources: ManagedResourceService,
    kind: DeploymentKind,
    key: str,
    capabilities: LLMCapabilities | None = None,
):
    credential = await resources.create_credential(
        f"{key}-credential", "secret", "test"
    )
    if kind in {DeploymentKind.LLM, DeploymentKind.REALTIME}:
        connection = await resources.create_connection(
            f"{key}-connection",
            "azure_openai",
            credential.ref,
            {"endpoint": "https://example.openai.azure.com"},
            True,
            "test",
        )
        config = (
            {"deployment_name": key, "model": key, "api_version": "2025-01-01-preview"}
            if kind is DeploymentKind.LLM
            else {"deployment_name": key}
        )
    else:
        connection = await resources.create_connection(
            f"{key}-connection", "elevenlabs", credential.ref, {}, True, "test"
        )
        config = {"model_id": key}
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


def cascade_policy(strategy: str) -> dict[str, object]:
    stt_commit: dict[str, object] = {"strategy": strategy}
    if strategy == "provider_vad":
        stt_commit["provider_vad"] = {
            "threshold": 0.5,
            "silence_threshold_seconds": 0.35,
            "min_speech_ms": 100,
            "min_silence_ms": 350,
        }
    return {
        "speech_activity": {
            "min_speech_seconds": 0.05,
            "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "stt_commit": stt_commit,
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


def realtime_policy(
    realtime_ref, transcription_ref, strategy: str = "server_vad"
) -> dict[str, object]:
    turn_completion = (
        {"strategy": strategy, "activation_threshold": 0.5, "silence_duration_ms": 200}
        if strategy == "server_vad"
        else {"strategy": strategy, "eagerness": "auto"}
    )
    return {
        "deployment_ref": str(realtime_ref),
        "input_transcription": {"deployment_ref": str(transcription_ref)},
        "default_voice": "marin",
        "turn_completion": turn_completion,
        "interruption": {"enabled": True},
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
            1,
            None,
            None,
            "test",
        )
        with pytest.raises(ManagedResourceNotFound):
            await components.publish_draft(address, draft.version, "test")
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == 0
            )

        terra = await deployment(
            resources, DeploymentKind.LLM, "terra-prod", LLMCapabilities(False, True)
        )
        draft = await components.save_draft(
            address,
            {
                "deployment_ref": str(terra.ref.value),
                "reasoning_effort": "high",
                "max_completion_tokens": 10,
            },
            1,
            draft.version,
            None,
            "test",
        )
        revision = await components.publish_draft(address, draft.version, "test")
        assert revision.value.deployment_ref == terra.ref.value
        draft = await components.save_draft(
            address,
            {
                "deployment_ref": str(terra.ref.value),
                "temperature": 0.2,
                "max_completion_tokens": 10,
            },
            1,
            None,
            revision.revision_id,
            "test",
        )
        with pytest.raises(InvalidComponentValue, match="temperature"):
            await components.publish_draft(address, draft.version, "test")
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_tenant_runtime_components_publish_and_rollback_independently(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, _ = services(database)
    architecture = ComponentAddress(
        ComponentKind("runtime.architecture.policy"), TenantScope("tenant-runtime")
    )
    speech = ComponentAddress(
        ComponentKind("runtime.speech.overrides"), TenantScope("tenant-runtime")
    )
    try:
        architecture_draft = await components.save_draft(
            architecture,
            {"architectures": ["realtime", "cascade"]},
            1,
            None,
            None,
            "test",
        )
        architecture_first = await components.publish_draft(
            architecture, architecture_draft.version, "test"
        )

        speech_draft = await components.save_draft(
            speech,
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": "marin"},
            },
            1,
            None,
            None,
            "test",
        )
        speech_first = await components.publish_draft(
            speech, speech_draft.version, "test"
        )
        assert (await components.get_active(architecture)).revision_id == (
            architecture_first.revision_id
        )
        assert len(await components.list_revisions(architecture)) == 1

        architecture_draft = await components.save_draft(
            architecture,
            {"architectures": ["cascade"]},
            1,
            None,
            architecture_first.revision_id,
            "test",
        )
        await components.publish_draft(architecture, architecture_draft.version, "test")
        assert (await components.get_active(speech)).revision_id == (
            speech_first.revision_id
        )
        assert len(await components.list_revisions(speech)) == 1

        restored = await components.rollback(
            architecture, architecture_first.revision_number, "test"
        )
        assert restored.value.architectures == ["realtime", "cascade"]
        assert (await components.get_active(speech)).revision_id == (
            speech_first.revision_id
        )

        async with database.sessions() as session:
            events = (await session.scalars(select(OutboxMessage))).all()
            revisions = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
        published = [
            ConfigurationComponentPublishedV1.model_validate(event.payload)
            for event in events
        ]
        assert all(
            event.event_type == COMPONENT_PUBLISHED_EVENT_TYPE for event in events
        )
        assert [event.payload.component_kind for event in published].count(
            "runtime.architecture.policy"
        ) == 3
        assert [event.payload.component_kind for event in published].count(
            "runtime.speech.overrides"
        ) == 1

        with pytest.raises(InvalidComponentValue):
            await components.save_draft(
                ComponentAddress(
                    ComponentKind("runtime.architecture.policy"),
                    TenantScope("invalid-runtime"),
                ),
                {"architectures": []},
                1,
                None,
                None,
                "test",
            )
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revisions
            )
            assert await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            ) == len(events)
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
            resources,
            DeploymentKind.LLM,
            "rollback-terra",
            LLMCapabilities(False, True),
        )
        first_draft = await components.save_draft(
            address,
            {
                "deployment_ref": str(terra.ref.value),
                "reasoning_effort": "high",
                "max_completion_tokens": 10,
            },
            1,
            None,
            None,
            "test",
        )
        first = await components.publish_draft(address, first_draft.version, "test")
        updated = await resources.update_deployment(
            terra.ref,
            terra.connection_ref,
            terra.deployment_config,
            terra.generation,
            "test",
            LLMCapabilities(True, False),
        )
        second_draft = await components.save_draft(
            address,
            {
                "deployment_ref": str(updated.ref.value),
                "temperature": 0.2,
                "max_completion_tokens": 10,
            },
            1,
            None,
            first.revision_id,
            "test",
        )
        second = await components.publish_draft(address, second_draft.version, "test")
        async with database.sessions() as session:
            revisions = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
            events = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        with pytest.raises(InvalidComponentValue, match="reasoning_effort"):
            await components.rollback(address, first.revision_number, "test")
        assert (await components.get_active(address)).revision_id == second.revision_id
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revisions
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == events
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_cascade_provider_vad_revalidates_current_stt_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    stt_address = ComponentAddress(
        ComponentKind("runtime.stt.defaults"), PlatformScope()
    )
    cascade_address = ComponentAddress(
        ComponentKind("runtime.cascade.execution.defaults"), PlatformScope()
    )
    try:
        stt = await deployment(resources, DeploymentKind.STT, "cascade-scribe")
        stt_draft = await components.save_draft(
            stt_address,
            {"deployment_ref": str(stt.ref.value)},
            1,
            None,
            None,
            "test",
        )
        await components.publish_draft(stt_address, stt_draft.version, "test")
        provider_draft = await components.save_draft(
            cascade_address,
            cascade_policy("provider_vad"),
            1,
            None,
            None,
            "test",
        )
        provider_revision = await components.publish_draft(
            cascade_address, provider_draft.version, "test"
        )

        async with database.sessions.begin() as session:
            connection = await session.get(ProviderConnection, stt.connection_ref.value)
            assert connection is not None
            connection.provider_kind = "unsupported_stt"

        local_draft = await components.save_draft(
            cascade_address,
            cascade_policy("local_vad"),
            1,
            None,
            provider_revision.revision_id,
            "test",
        )
        local_revision = await components.publish_draft(
            cascade_address, local_draft.version, "test"
        )
        failed_draft = await components.save_draft(
            cascade_address,
            cascade_policy("provider_vad"),
            1,
            None,
            local_revision.revision_id,
            "test",
        )
        async with database.sessions() as session:
            revisions = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
            events = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )

        with pytest.raises(InvalidComponentValue, match="does not support"):
            await components.publish_draft(
                cascade_address, failed_draft.version, "test"
            )
        assert (
            await components.get_active(cascade_address)
        ).revision_id == local_revision.revision_id
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revisions
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == events
            )

        await components.discard_draft(cascade_address, failed_draft.version)
        with pytest.raises(InvalidComponentValue, match="does not support"):
            await components.rollback(
                cascade_address, provider_revision.revision_number, "test"
            )
        assert (
            await components.get_active(cascade_address)
        ).revision_id == local_revision.revision_id
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revisions
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == events
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_realtime_activation_validation_and_lifecycle_are_atomic(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components, resources = services(database)
    address = ComponentAddress(
        ComponentKind("runtime.realtime.execution.defaults"), PlatformScope()
    )
    try:
        credential = await resources.create_credential("realtime", "secret", "test")
        first = await resources.create_connection(
            "azure-realtime",
            "azure_openai",
            credential.ref,
            {"endpoint": "https://first.openai.azure.com"},
            True,
            "test",
        )
        second = await resources.create_connection(
            "azure-realtime-other",
            "azure_openai",
            credential.ref,
            {"endpoint": "https://second.openai.azure.com"},
            True,
            "test",
        )

        async def realtime(
            key: str, capabilities: RealtimeCapabilities, enabled: bool = True
        ):
            return await resources.create_deployment(
                key,
                first.ref,
                DeploymentKind.REALTIME,
                {"deployment_name": key},
                enabled,
                "test",
                realtime_capabilities=capabilities,
            )

        async def transcription(
            key: str,
            capabilities: STTCapabilities,
            enabled: bool = True,
            other: bool = False,
        ):
            return await resources.create_deployment(
                key,
                second.ref if other else first.ref,
                DeploymentKind.STT,
                {"deployment_name": key},
                enabled,
                "test",
                stt_capabilities=capabilities,
            )

        model = await realtime("realtime-good", RealtimeCapabilities(True, True))
        no_server = await realtime(
            "realtime-no-server", RealtimeCapabilities(False, True)
        )
        no_semantic = await realtime(
            "realtime-no-semantic", RealtimeCapabilities(True, False)
        )
        disabled_model = await realtime(
            "realtime-disabled", RealtimeCapabilities(True, True), False
        )
        transcript = await transcription(
            "transcription-good", STTCapabilities(False, True)
        )
        cascade_only = await transcription(
            "transcription-cascade", STTCapabilities(True, False)
        )
        disabled_transcript = await transcription(
            "transcription-disabled", STTCapabilities(False, True), False
        )
        different_connection = await transcription(
            "transcription-other", STTCapabilities(False, True), other=True
        )

        draft_version = None
        active_revision_id = None

        async def rejected(value: dict[str, object], match: str) -> None:
            nonlocal draft_version
            draft = await components.save_draft(
                address, value, 1, draft_version, active_revision_id, "test"
            )
            draft_version = draft.version
            async with database.sessions() as session:
                revision_count = await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                event_count = await session.scalar(
                    select(func.count()).select_from(OutboxMessage)
                )
            with pytest.raises(
                (InvalidComponentValue, ManagedResourceNotFound), match=match
            ):
                await components.publish_draft(address, draft.version, "test")
            async with database.sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ConfigurationComponentRevision)
                    )
                    == revision_count
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(OutboxMessage)
                    )
                    == event_count
                )

        cases = [
            (
                realtime_policy(uuid4(), transcript.ref.value),
                "realtime deployment not found",
            ),
            (
                realtime_policy(transcript.ref.value, transcript.ref.value),
                "deployment_kind=realtime",
            ),
            (
                realtime_policy(model.ref.value, uuid4()),
                "transcription deployment not found",
            ),
            (realtime_policy(model.ref.value, model.ref.value), "deployment_kind=stt"),
            (
                realtime_policy(model.ref.value, cascade_only.ref.value),
                "realtime input transcription",
            ),
            (
                realtime_policy(disabled_model.ref.value, transcript.ref.value),
                "realtime deployment is disabled",
            ),
            (
                realtime_policy(model.ref.value, disabled_transcript.ref.value),
                "transcription deployment is disabled",
            ),
            (
                realtime_policy(model.ref.value, different_connection.ref.value),
                "same provider connection",
            ),
            (
                realtime_policy(no_server.ref.value, transcript.ref.value),
                "does not support server_vad",
            ),
        ]
        for value, match in cases:
            await rejected(value, match)

        draft = await components.save_draft(
            address,
            realtime_policy(model.ref.value, transcript.ref.value),
            1,
            draft_version,
            None,
            "test",
        )
        server_revision = await components.publish_draft(address, draft.version, "test")
        active_revision_id, draft_version = server_revision.revision_id, None
        await rejected(
            realtime_policy(
                no_semantic.ref.value, transcript.ref.value, "semantic_vad"
            ),
            "does not support semantic_vad",
        )
        draft = await components.save_draft(
            address,
            realtime_policy(model.ref.value, transcript.ref.value, "semantic_vad"),
            1,
            draft_version,
            active_revision_id,
            "test",
        )
        semantic_revision = await components.publish_draft(
            address, draft.version, "test"
        )
        draft = await components.save_draft(
            address,
            realtime_policy(model.ref.value, transcript.ref.value),
            1,
            None,
            semantic_revision.revision_id,
            "test",
        )
        current = await components.publish_draft(address, draft.version, "test")

        async with database.sessions() as session:
            events = (
                await session.scalars(
                    select(OutboxMessage).where(OutboxMessage.component_id.is_not(None))
                )
            ).all()
        assert len(events) == 3
        assert all(
            event.event_type == COMPONENT_PUBLISHED_EVENT_TYPE for event in events
        )
        assert all(
            ConfigurationComponentPublishedV1.model_validate(
                event.payload
            ).payload.component_kind
            == "runtime.realtime.execution.defaults"
            for event in events
        )

        await resources.update_deployment(
            model.ref,
            model.connection_ref,
            model.deployment_config,
            model.generation,
            "test",
            realtime_capabilities=RealtimeCapabilities(True, False),
        )
        async with database.sessions() as session:
            revision_count = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
            event_count = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        with pytest.raises(InvalidComponentValue, match="semantic_vad"):
            await components.rollback(
                address, semantic_revision.revision_number, "test"
            )
        assert (await components.get_active(address)).revision_id == current.revision_id
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revision_count
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == event_count
            )
    finally:
        await database.close()
