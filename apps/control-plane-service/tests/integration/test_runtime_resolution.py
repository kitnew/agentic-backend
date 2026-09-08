from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import jwt
import pytest
from control_plane.application.command_support import IdempotencyKeyReused
from control_plane.application.components import ComponentService
from control_plane.application.execution_materialization import (
    BackendExecutionContext,
    ExecutionMaterializationService,
    HandoffExecutionMaterial,
    IntegrationExecutionMaterial,
    RuntimeSecretMaterial,
    RuntimeSecretSlot,
    VoiceExecutionContext,
    WorkerExecutionContext,
)
from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.bootstrap import create_app
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.managed_resource_errors import (
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.registries import ProviderKindRegistry
from control_plane.domain.runtime_resolution import (
    ResolvedCascadeRuntime,
    RuntimeResolutionError,
)
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.live_components import (
    SqlAlchemyLiveComponentRepository,
)
from control_plane.infrastructure.persistence.models import (
    Credential,
    HandoffDestination,
    IdempotencyReplay,
    IntegrationConnection,
    PhoneNumberAssignment,
    ProfileCatalogEntry,
)
from control_plane.infrastructure.persistence.models import (
    ExecutionSnapshot as SnapshotRow,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)
from control_plane.settings import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from .test_system_configuration import KEY, desired, setup


def service_token(service: str, scopes: list[str], secret: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "service": service,
            "sub": service,
            "aud": "control-plane-service",
            "iat": now,
            "exp": now + timedelta(minutes=1),
            "scopes": scopes,
        },
        secret,
        algorithm="HS256",
    )


def api_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        control_plane_encryption_key=KEY,
        voice_agent_service_secret="v" * 32,
        backend_core_service_secret="b" * 32,
    )


def component_service(database: Database):
    registry = default_component_definition_registry()
    return ComponentService(
        registry,
        cast(ComponentRepository, SqlAlchemyComponentRepository(database.sessions)),
    )


async def configure_tenant(
    database, components, tenant_id, actions: dict[str, object] | None = None
):
    actions = actions or {}
    async with database.sessions.begin() as session:
        session.add(
            ProfileCatalogEntry(
                key="default",
                name="Default",
                description="Default profile",
                status="enabled",
                generation=1,
                updated_by="test",
            )
        )
    versioned = (
        (
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            {"content": "system"},
        ),
        (
            ComponentAddress(ComponentKind("ProfilePrompt"), ProfileScope("default")),
            {"content": "profile"},
        ),
        (
            ComponentAddress(ComponentKind("TenantPrompt"), TenantScope(tenant_id)),
            {"content": "tenant"},
        ),
        (
            ComponentAddress(ComponentKind("Knowledge"), TenantScope(tenant_id)),
            {"content": "knowledge"},
        ),
        (
            ComponentAddress(ComponentKind("AgentPersonality"), TenantScope(tenant_id)),
            {
                "identity": "default",
                "display_name": "Amélia",
                "greeting": "Dobrý deň",
                "conversation_scope": "property_only",
            },
        ),
        (
            ComponentAddress(ComponentKind("BusinessInfo"), TenantScope(tenant_id)),
            {
                "business": {"name": "Hotel", "type": "hotel"},
                "contact": {"phones": [], "emails": []},
                "localization": {
                    "default_locale": "sk-SK",
                    "timezone": "Europe/Bratislava",
                },
            },
        ),
        (
            ComponentAddress(
                ComponentKind("ActionsDefinition"), TenantScope(tenant_id)
            ),
            {"actions": actions},
        ),
    )
    for address, value in versioned:
        draft = await components.save_draft(address, value, None, None, "test")
        await components.publish_draft(address, draft.version, "test")
    async with database.sessions.begin() as session:
        live = SqlAlchemyLiveComponentRepository(session)
        for kind, value in (
            ("Architecture", {"architecture_key": "cascade"}),
            ("RuntimeOverrides", {"stt": {"keyterms": ["Penzión Grand"]}}),
            ("ProfileReference", {"profile_key": "default"}),
            (
                "ActionsAvailability",
                {"actions": {key: True for key in actions}},
            ),
        ):
            await live.set(
                ComponentAddress(ComponentKind(kind), TenantScope(tenant_id)),
                value,
                1,
                "test",
            )


def runtime_action(integration_key: str, phase: str = "runtime") -> dict[str, object]:
    execution = {
        "integration_key": integration_key,
        "method": "POST",
        "request": {"codec": "json"},
        "response": {"codec": "json"},
        "timeout_seconds": 5,
    }
    if phase == "post_call":
        return {
            "phase": "post_call",
            "artifact_inputs": {
                "transcript": {
                    "artifact": "transcript",
                    "representation": "plain_text",
                }
            },
            "execution": execution,
        }
    return {
        "phase": "runtime",
        "description": "Check availability",
        "announcement": "One moment",
        "agent_input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "execution": execution,
    }


def execution_service(database: Database) -> ExecutionMaterializationService:
    registry = default_component_definition_registry()
    reader = SqlAlchemyRuntimeResolutionReader(database.sessions)
    runtime = RuntimeResolver(registry, ProviderKindRegistry(), reader)
    return ExecutionMaterializationService(
        database.sessions,
        CredentialCipher(KEY),
        SqlAlchemyExecutionSnapshotRepository(database.sessions),
        ExecutionResolver(registry, runtime),
        reader,
    )


@pytest.mark.asyncio
async def test_runtime_resolution_is_repeatable_read_and_read_only(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    registry = default_component_definition_registry()
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
        await configure_tenant(database, components, "runtime-integration")

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
            "Architecture",
            "RuntimeOverrides",
            "ProfileReference",
            "ActionsAvailability",
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
async def test_slice_12_execution_is_frozen_idempotent_and_snapshot_projected(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    integration_id, handoff_id = uuid4(), uuid4()
    actions = {
        "booking.check": runtime_action("booking"),
        "booking.archive": runtime_action("booking", "post_call"),
    }
    try:
        await system.apply(desired(refs, voice="voice-a"), "*", "test", "system-a")
        async with database.sessions.begin() as session:
            credential_id = await session.scalar(select(Credential.id))
            assert credential_id is not None
            session.add_all(
                [
                    IntegrationConnection(
                        id=integration_id,
                        tenant_id="slice-12",
                        key="booking",
                        integration_kind="http",
                        config={
                            "endpoint": "https://example.com",
                            "headers": {},
                            "authentication": {
                                "type": "api_key_header",
                                "header_name": "X-Api-Key",
                            },
                            "security": {"additional_allowed_hosts": []},
                        },
                        credential_id=credential_id,
                        enabled=True,
                        generation=1,
                        created_by="test",
                        updated_by="test",
                    ),
                    HandoffDestination(
                        id=handoff_id,
                        tenant_id="slice-12",
                        key="reception",
                        description="Reception",
                        phone_number="+421900000001",
                        enabled=True,
                        generation=1,
                        created_by="test",
                        updated_by="test",
                    ),
                    PhoneNumberAssignment(
                        tenant_id="slice-12",
                        phone_number="+421900000002",
                        enabled=True,
                        generation=1,
                        created_by="test",
                        updated_by="test",
                    ),
                ]
            )
        await configure_tenant(database, components, "slice-12", actions)
        app = create_app(api_settings(migrated_database_url), database=database)
        service = app.state.execution_materialization
        headers = {
            "Authorization": "Bearer "
            + service_token(
                "backend-core",
                [
                    "execution:create",
                    "execution:voice-context:read",
                    "execution:worker-context:read",
                    "integration-material:read",
                    "handoff-material:read",
                    "telephony:resolve",
                ],
                "b" * 32,
            ),
            "Idempotency-Key": "execution-1",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/v1/executions",
                headers=headers,
                json={"tenant_id": "slice-12", "context": {"call_id": "call-1"}},
            )
            replay_response = await client.post(
                "/internal/v1/executions",
                headers=headers,
                json={"tenant_id": "slice-12", "context": {"call_id": "call-1"}},
            )
        assert response.status_code == replay_response.status_code == 201
        created = BackendExecutionContext.model_validate(response.json())
        replay = BackendExecutionContext.model_validate(replay_response.json())
        assert replay == created
        with pytest.raises(IdempotencyKeyReused):
            await service.create_execution(
                "slice-12",
                {"call_id": "different"},
                principal="backend-core",
                idempotency_key="execution-1",
            )
        assert set(type(created).model_fields) == {
            "execution_id",
            "tenant_id",
            "architecture",
            "backend_actions",
            "handoff",
            "metadata",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            voice_response = await client.get(
                f"/internal/v1/executions/{created.execution_id}/voice-context",
                headers=headers,
            )
            runtime_worker_response = await client.get(
                f"/internal/v1/executions/{created.execution_id}/worker-context",
                headers=headers,
                params={"action_key": "booking.check"},
            )
            post_call_worker_response = await client.get(
                f"/internal/v1/executions/{created.execution_id}/worker-context",
                headers=headers,
                params={"action_key": "booking.archive"},
            )
        voice = VoiceExecutionContext.model_validate(voice_response.json())
        runtime_worker = WorkerExecutionContext.model_validate(
            runtime_worker_response.json()
        )
        post_call_worker = WorkerExecutionContext.model_validate(
            post_call_worker_response.json()
        )
        voice_headers = {
            "Authorization": "Bearer "
            + service_token("voice-agent", ["runtime-secret:materialize"], "v" * 32)
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            route_response = await client.get(
                "/internal/v1/telephony/inbound-route",
                headers=headers,
                params={"phone_number": "+421900000002"},
            )
            integration_response = await client.post(
                f"/internal/v1/executions/{created.execution_id}/integrations/booking/material",
                headers=headers,
            )
            handoff_response = await client.post(
                f"/internal/v1/executions/{created.execution_id}/handoff/reception/material",
                headers=headers,
            )
            secret_response = await client.post(
                f"/internal/v1/executions/{created.execution_id}/secrets/llm",
                headers=voice_headers,
            )
        assert route_response.json()["tenant_id"] == created.tenant_id
        assert IntegrationExecutionMaterial.model_validate(integration_response.json())
        assert HandoffExecutionMaterial.model_validate(handoff_response.json())
        assert RuntimeSecretMaterial.model_validate(secret_response.json())
        assert isinstance(created, BackendExecutionContext)
        assert isinstance(voice, VoiceExecutionContext)
        assert isinstance(runtime_worker, WorkerExecutionContext)
        assert set(type(voice).model_fields) == {
            "execution_id",
            "tenant",
            "agent",
            "architecture",
            "prompts",
            "runtime",
            "actions",
            "handoff",
        }
        assert set(type(runtime_worker).model_fields) == {
            "execution_id",
            "tenant_id",
            "action",
            "integration",
        }
        assert voice.execution_id == runtime_worker.execution_id == created.execution_id
        assert runtime_worker.action["phase"] == "runtime"
        assert post_call_worker.action["phase"] == "post_call"
        assert runtime_worker.integration == {"semantic_key": "booking"}
        assert "connection_id" not in str(runtime_worker)
        assert "provenance" not in str((created, voice, runtime_worker))
        assert "credential" not in str(voice).lower()
        assert "_ref" not in str(voice).lower()
        with pytest.raises(ManagedResourceNotFound):
            await service.worker_context(created.execution_id, "unknown")

        await system.apply(
            desired(refs, voice="voice-b"),
            system.concurrency_token(await system.get()),
            "test",
            "system-b",
        )
        service._reader = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            frozen_response = await client.get(
                f"/internal/v1/executions/{created.execution_id}/voice-context",
                headers=headers,
            )
            frozen_worker_response = await client.get(
                f"/internal/v1/executions/{created.execution_id}/worker-context",
                headers=headers,
                params={"action_key": "booking.check"},
            )
            replay_after_mutation_response = await client.post(
                "/internal/v1/executions",
                headers=headers,
                json={"tenant_id": "slice-12", "context": {"call_id": "call-1"}},
            )
        frozen = VoiceExecutionContext.model_validate(frozen_response.json())
        frozen_worker = WorkerExecutionContext.model_validate(
            frozen_worker_response.json()
        )
        replay_after_mutation = BackendExecutionContext.model_validate(
            replay_after_mutation_response.json()
        )
        assert frozen == voice
        assert frozen_worker == runtime_worker
        assert replay_after_mutation == created
        assert frozen.runtime["tts"]["voice"] == "voice-a"

        integration = await service.integration_material(
            created.execution_id, "booking"
        )
        handoff = await service.handoff_material(created.execution_id, "reception")
        secret = await service.runtime_secret(
            created.execution_id, RuntimeSecretSlot.LLM
        )
        assert isinstance(integration, IntegrationExecutionMaterial)
        assert isinstance(handoff, HandoffExecutionMaterial)
        assert isinstance(secret, RuntimeSecretMaterial)
        assert set(type(integration).model_fields) == {
            "integration_kind",
            "config",
            "secret",
        }
        assert set(type(secret).model_fields) == {"slot", "secret"}
        assert integration.secret == "secret"
        assert set(type(handoff).model_fields) == {
            "destination_key",
            "phone_number",
        }
        with pytest.raises(ManagedResourceNotFound):
            await service.integration_material(created.execution_id, "other")
        with pytest.raises(ManagedResourceNotFound):
            await service.handoff_material(created.execution_id, "other")

        async with database.sessions.begin() as session:
            credential = await session.get(Credential, credential_id)
            assert credential is not None
            credential.status = "revoked"
            credential.active_version_id = None
            credential.revoked_at = datetime.now(UTC)
            credential.revoked_by = "test"
        with pytest.raises(ManagedResourceConflict):
            await service.integration_material(created.execution_id, "booking")
        with pytest.raises(ManagedResourceConflict):
            await service.runtime_secret(created.execution_id, RuntimeSecretSlot.LLM)

        async with database.sessions.begin() as session:
            connection = await session.get(IntegrationConnection, integration_id)
            assert connection is not None
            connection.enabled = False
            destination = await session.get(HandoffDestination, handoff_id)
            assert destination is not None
            destination.enabled = False
        with pytest.raises(ManagedResourceConflict):
            await service.integration_material(created.execution_id, "booking")
        with pytest.raises(ManagedResourceConflict):
            await service.handoff_material(created.execution_id, "reception")

        async with database.sessions() as session:
            snapshot_count = await session.scalar(
                select(func.count()).select_from(SnapshotRow)
            )
            replay_count = await session.scalar(
                select(func.count())
                .select_from(IdempotencyReplay)
                .where(IdempotencyReplay.operation == "execution.create")
            )
            payload = await session.scalar(
                select(SnapshotRow.payload).where(
                    SnapshotRow.snapshot_id == created.execution_id
                )
            )
        assert (snapshot_count, replay_count) == (1, 1)
        serialized = str(payload).lower()
        assert "'secret'" not in serialized
        assert all(
            value not in serialized
            for value in (
                "ciphertext",
                "nonce",
                "key_id",
                "active_version_id",
                "active_secret_version_number",
            )
        )

        with pytest.raises(DBAPIError, match="execution snapshot is immutable"):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.execution_snapshots "
                        "SET architecture='realtime' WHERE snapshot_id=:id"
                    ),
                    {"id": created.execution_id},
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_slice_12_failed_creation_persists_no_snapshot_or_replay(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    try:
        await system.apply(desired(refs), "*", "test", "system")
        await configure_tenant(
            database,
            components,
            "missing",
            {"booking.check": runtime_action("missing-integration")},
        )
        service = execution_service(database)
        with pytest.raises(RuntimeResolutionError):
            await service.create_execution(
                "missing",
                {},
                principal="service:backend",
                idempotency_key="missing",
            )
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SnapshotRow)) == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IdempotencyReplay)
                    .where(IdempotencyReplay.operation == "execution.create")
                )
                == 0
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_slice_12_replay_failure_rolls_back_snapshot(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    try:
        await system.apply(desired(refs), "*", "test", "system")
        await configure_tenant(database, components, "replay-failure")
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_execution_replay() "
                    "RETURNS trigger LANGUAGE plpgsql AS "
                    "'BEGIN IF NEW.operation = ''execution.create'' THEN "
                    "RAISE EXCEPTION ''execution replay failed''; END IF; "
                    "RETURN NEW; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_execution_replay BEFORE INSERT ON "
                    "control_plane.idempotency_replays FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_execution_replay()"
                )
            )

        with pytest.raises(DBAPIError, match="execution replay failed"):
            await execution_service(database).create_execution(
                "replay-failure",
                {},
                principal="service:backend",
                idempotency_key="failure",
            )

        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SnapshotRow)) == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IdempotencyReplay)
                    .where(IdempotencyReplay.operation == "execution.create")
                )
                == 0
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_slice_12_creation_reads_one_state_during_concurrent_mutation(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    components = component_service(database)
    system, _, refs = await setup(database)
    try:
        applied = await system.apply(
            desired(refs, voice="voice-a"), "*", "test", "system-a"
        )
        await configure_tenant(database, components, "repeatable")
        base = SqlAlchemyRuntimeResolutionReader(database.sessions)

        class MutatingReader:
            async def load_in_session(self, session, tenant_id):
                before = await base.load_in_session(session, tenant_id)
                await system.apply(
                    desired(refs, voice="voice-b"),
                    system.concurrency_token(applied.configuration),
                    "test",
                    "system-b",
                )
                after = await base.load_in_session(session, tenant_id)
                assert after == before
                return after

        reader = MutatingReader()
        registry = default_component_definition_registry()
        runtime = RuntimeResolver(registry, ProviderKindRegistry(), reader)
        service = ExecutionMaterializationService(
            database.sessions,
            CredentialCipher(KEY),
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
            ExecutionResolver(registry, runtime),
            reader,
        )
        created = await service.create_execution(
            "repeatable",
            {},
            principal="service:backend",
            idempotency_key="repeatable",
        )

        voice = await service.voice_context(created.execution_id)
        assert voice.runtime["tts"]["voice"] == "voice-a"
        assert (await system.get()).tts_defaults.default_voice_id == "voice-b"
    finally:
        await database.close()
