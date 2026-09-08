import base64
from contextlib import asynccontextmanager

import pytest
from control_plane.application.credentials import CredentialService
from control_plane.application.live_components import LiveComponentService
from control_plane.application.providers import (
    ProviderService,
    ProviderValidationResult,
)
from control_plane.application.system_configuration import (
    SystemConfigurationDesired,
    SystemConfigurationError,
    SystemConfigurationService,
)
from control_plane.domain.components import ComponentAddress, ComponentKind, SystemScope
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.managed_resource_errors import ManagedResourceConflict
from control_plane.domain.managed_resources import (
    DeploymentKind,
    LLMCapabilities,
    PlatformCredentialScope,
    RealtimeCapabilities,
    STTCapabilities,
    TTSCapabilities,
)
from control_plane.domain.registries import DeploymentKindRegistry, ProviderKindRegistry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponent,
    ConfigurationComponentDraft,
    ConfigurationComponentRevision,
    IdempotencyReplay,
    LiveComponent,
)
from control_plane.infrastructure.persistence.provider_transactions import (
    provider_command_scope,
)
from control_plane.infrastructure.persistence.system_configuration_transactions import (
    system_configuration_command_scope,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

KEY = base64.b64encode(b"0" * 32).decode()


class Validator:
    async def validate_connection(self, *_args):
        return ProviderValidationResult(True, True)

    async def validate_deployment(self, *_args):
        return ProviderValidationResult(True, True)


async def setup(database):
    cipher = CredentialCipher(KEY)
    credentials = CredentialService(credential_command_scope(database.sessions, cipher))
    providers = ProviderService(
        provider_command_scope(database.sessions, cipher),
        ProviderKindRegistry(),
        DeploymentKindRegistry(),
        Validator(),
    )
    credential = await credentials.create(
        PlatformCredentialScope(), "system", "secret", "alice", "credential"
    )
    connection = await providers.create_connection(
        "azure",
        "azure_openai",
        credential.ref,
        {"endpoint": "https://example.openai.azure.com"},
        "alice",
        "connection",
    )
    connection = await providers.enable_connection(
        connection.ref,
        providers.concurrency_token(connection),
        "alice",
        "connection-enable",
    )
    tts_connection = await providers.create_connection(
        "eleven", "elevenlabs", credential.ref, {}, "alice", "tts-connection"
    )
    tts_connection = await providers.enable_connection(
        tts_connection.ref,
        providers.concurrency_token(tts_connection),
        "alice",
        "tts-connection-enable",
    )
    specs = {
        "stt": (
            DeploymentKind.STT,
            STTCapabilities(True, True),
            {"deployment_name": "stt"},
        ),
        "llm": (
            DeploymentKind.LLM,
            LLMCapabilities(True, True),
            {"deployment_name": "llm", "model": "gpt", "api_version": "v1"},
        ),
        "tts": (DeploymentKind.TTS, TTSCapabilities(), {"model_id": "tts"}),
        "realtime": (
            DeploymentKind.REALTIME,
            RealtimeCapabilities(True, True),
            {"deployment_name": "realtime"},
        ),
    }
    refs = {}
    for key, (kind, capabilities, config) in specs.items():
        deployment = await providers.create_deployment(
            key,
            tts_connection.ref if kind is DeploymentKind.TTS else connection.ref,
            kind,
            config,
            capabilities,
            "alice",
            f"{key}-create",
        )
        deployment = await providers.enable_deployment(
            deployment.ref,
            providers.concurrency_token(deployment),
            "alice",
            f"{key}-enable",
        )
        refs[key] = deployment.ref.value
    return (
        SystemConfigurationService(
            default_component_definition_registry(),
            system_configuration_command_scope(database.sessions, cipher),
        ),
        providers,
        refs,
    )


def desired(refs, voice="marin"):
    return SystemConfigurationDesired.model_validate(
        {
            "stt_defaults": {"deployment_ref": str(refs["stt"])},
            "llm_defaults": {
                "deployment_ref": str(refs["llm"]),
                "temperature": 0.5,
                "reasoning_effort": "medium",
                "max_completion_tokens": 100,
            },
            "tts_defaults": {
                "deployment_ref": str(refs["tts"]),
                "default_voice_id": voice,
            },
            "realtime_defaults": {
                "deployment_ref": str(refs["realtime"]),
                "input_transcription": {"deployment_ref": str(refs["stt"])},
                "default_voice": "marin",
                "turn_completion": {"strategy": "semantic_vad"},
                "interruption": {"enabled": True},
            },
            "policies": {
                "cascade": {
                    "speech_activity": {
                        "min_speech_seconds": 0.1,
                        "min_silence_seconds": 0.2,
                        "activation_threshold": 0.5,
                    },
                    "stt_commit": {"strategy": "local_vad"},
                    "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.2},
                    "interruption": {
                        "enabled": True,
                        "min_duration_seconds": 0,
                        "min_words": 0,
                        "false_interruption_timeout_seconds": 0,
                        "resume_after_false_interruption": True,
                    },
                    "response_scheduling": {
                        "preemptive_generation": False,
                        "preemptive_tts": False,
                    },
                    "tokenizer": {"min_sentence_chars": 3},
                }
            },
        }
    )


@pytest.mark.asyncio
async def test_plan_does_not_mutate_any_database_state(migrated_database_url):
    database = Database(migrated_database_url)
    try:
        service, _, refs = await setup(database)
        async with database.sessions() as session:
            before = (
                await session.scalar(select(func.count()).select_from(LiveComponent)),
                await session.scalar(
                    select(func.count()).select_from(IdempotencyReplay)
                ),
            )
        plan = await service.plan(desired(refs))
        assert plan.valid
        async with database.sessions() as session:
            after = (
                await session.scalar(select(func.count()).select_from(LiveComponent)),
                await session.scalar(
                    select(func.count()).select_from(IdempotencyReplay)
                ),
            )
        assert after == before
        assert before[0] == 0

        applied = await service.apply(
            desired(refs), service.concurrency_token(None), "alice", "plan-proof-apply"
        )
        async with database.sessions() as session:
            before_rows = (
                await session.execute(
                    select(
                        LiveComponent.kind,
                        LiveComponent.value,
                        LiveComponent.generation,
                        LiveComponent.updated_at,
                        LiveComponent.updated_by,
                    ).order_by(LiveComponent.kind)
                )
            ).all()
            before_replays = await session.scalar(
                select(func.count()).select_from(IdempotencyReplay)
            )
        no_op = await service.plan(applied.configuration)
        async with database.sessions() as session:
            after_rows = (
                await session.execute(
                    select(
                        LiveComponent.kind,
                        LiveComponent.value,
                        LiveComponent.generation,
                        LiveComponent.updated_at,
                        LiveComponent.updated_by,
                    ).order_by(LiveComponent.kind)
                )
            ).all()
            after_replays = await session.scalar(
                select(func.count()).select_from(IdempotencyReplay)
            )
        assert no_op.valid and no_op.changes == ()
        assert after_rows == before_rows
        assert after_replays == before_replays
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_apply_has_five_unique_current_rows_and_no_versioned_side_effects(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    try:
        service, providers, refs = await setup(database)
        first = await service.apply(
            desired(refs), service.concurrency_token(None), "alice", "system-apply"
        )
        second = await service.apply(
            desired(refs), service.concurrency_token(None), "alice", "system-apply"
        )
        assert second == first
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(LiveComponent))
                == 5
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponent)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentDraft)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == 0
            )
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                session.add(
                    LiveComponent(
                        kind="TTSDefaults",
                        scope_type="system",
                        scope_key=None,
                        value={
                            "deployment_ref": str(refs["tts"]),
                            "default_voice_id": "duplicate",
                        },
                        schema_version=1,
                        generation=1,
                        updated_by="alice",
                    )
                )
                await session.flush()
        tts = next(
            item
            for item in await providers.list_deployments()
            if item.ref.value == refs["tts"]
        )
        with pytest.raises(ManagedResourceConflict, match="system configuration"):
            await providers.disable_deployment(
                tts.ref, providers.concurrency_token(tts), "alice", "disable-referenced"
            )
        stt = next(
            item
            for item in await providers.list_deployments()
            if item.ref.value == refs["stt"]
        )
        with pytest.raises(
            ManagedResourceConflict, match="invalidate system configuration"
        ):
            await providers.update_deployment(
                stt.ref,
                stt.connection_ref,
                stt.deployment_config,
                STTCapabilities(False, True),
                providers.concurrency_token(stt),
                "alice",
                "invalidate-stt",
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_low_level_live_write_uses_system_deployment_validation(
    migrated_database_url,
):
    database = Database(migrated_database_url)
    try:
        system, _, refs = await setup(database)
        live = LiveComponentService(
            default_component_definition_registry(),
            lambda _address: system._command_scope(),
            system.validate_live_component,
        )
        state = await live.set(
            ComponentAddress(ComponentKind("TTSDefaults"), SystemScope()),
            {"deployment_ref": str(refs["tts"]), "default_voice_id": "marin"},
            "*",
            "alice",
            "live-tts",
        )
        assert state.value.default_voice_id == "marin"
        with pytest.raises(SystemConfigurationError, match="deployment_kind=tts"):
            await live.set(
                ComponentAddress(ComponentKind("TTSDefaults"), SystemScope()),
                {"deployment_ref": str(refs["llm"]), "default_voice_id": "marin"},
                live.concurrency_token(state),
                "alice",
                "live-wrong-kind",
            )
        assert await live.get(state.address) == state
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_replay_write_failure_rolls_back_all_live_rows(migrated_database_url):
    database = Database(migrated_database_url)
    try:
        service, _, refs = await setup(database)
        real_scope = service._command_scope

        @asynccontextmanager
        async def failing_scope():
            async with real_scope() as (repository, replays):

                async def fail(*_args, **_kwargs):
                    raise RuntimeError("replay write failed")

                replays.add = fail
                yield repository, replays

        failing = SystemConfigurationService(
            default_component_definition_registry(), failing_scope
        )
        with pytest.raises(RuntimeError, match="replay write failed"):
            await failing.apply(
                desired(refs), failing.concurrency_token(None), "alice", "failed"
            )
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(LiveComponent))
                == 0
            )
    finally:
        await database.close()
