from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from contracts import (
    BackendExecutionContext,
    HandoffExecutionMaterial,
    IntegrationExecutionMaterial,
    RuntimeSecretMaterial,
    RuntimeSecretSlot,
    VoiceExecutionContext,
    WorkerExecutionContext,
)
from contracts.integration import HttpConnectionConfiguration
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    request_fingerprint,
)
from control_plane.application.execution_resolver import (
    ExecutionResolution,
    ExecutionResolver,
)
from control_plane.application.runtime_resolver import RuntimeResolutionReader
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.runtime_execution_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ExecutionSnapshot,
    assert_secret_free_payload,
    content_hash,
    snapshot_payload,
)
from control_plane.domain.runtime_resolution import (
    ResolvedCascadeRuntime,
    ResolvedProviderResource,
    ResolvedRuntime,
)
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from control_plane.infrastructure.persistence.models import (
    Credential,
    CredentialVersion,
    HandoffDestination,
    IntegrationConnection,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)

CREATE_EXECUTION_OPERATION = "execution.create"


class ExecutionMaterializationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: CredentialCipher | None,
        snapshots: SqlAlchemyExecutionSnapshotRepository,
        resolver: ExecutionResolver | None = None,
        reader: RuntimeResolutionReader | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._snapshots = snapshots
        self._resolver = resolver
        self._reader = reader

    async def create_execution(
        self,
        tenant_id: str,
        context: Mapping[str, object] | None,
        *,
        principal: str,
        idempotency_key: str,
    ) -> BackendExecutionContext:
        result = await self._create(
            tenant_id,
            context or {},
            principal=principal,
            idempotency_key=idempotency_key,
        )
        assert isinstance(result, BackendExecutionContext)
        return result

    async def _create(
        self,
        tenant_id: str,
        context: Mapping[str, object],
        *,
        principal: str | None,
        idempotency_key: str | None,
    ) -> BackendExecutionContext:
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "context": dict(context)}
        )
        async with self._sessions.begin() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            replays = SqlAlchemyIdempotencyRepository(session)
            if principal is not None and idempotency_key is not None:
                replay = await replays.get(
                    principal, CREATE_EXECUTION_OPERATION, idempotency_key
                )
                if replay is not None:
                    if replay.request_fingerprint != fingerprint:
                        raise IdempotencyKeyReused(
                            "idempotency key reused with a different request"
                        )
                    snapshot = await self._required_snapshot(
                        session, UUID(str(replay.logical_result["execution_id"]))
                    )
                    return self._backend(snapshot)

            if self._resolver is None or self._reader is None:
                raise RuntimeError("execution creation is not configured")
            resolution = self._resolver.resolve_state(
                tenant_id, await self._reader.load_in_session(session, tenant_id)
            )
            target = self._target_state(resolution, context)
            payload = snapshot_payload(target)
            assert_secret_free_payload(payload)
            snapshot = ExecutionSnapshot(
                uuid4(),
                SNAPSHOT_SCHEMA_VERSION,
                tenant_id,
                resolution.architecture,
                datetime.now(UTC),
                payload,
                content_hash(payload),
            )
            await self._snapshots.create(session, snapshot, payload)
            await session.flush()
            persisted = await self._required_snapshot(session, snapshot.execution_id)
            if principal is not None and idempotency_key is not None:
                await replays.add(
                    principal,
                    CREATE_EXECUTION_OPERATION,
                    idempotency_key,
                    fingerprint,
                    {"execution_id": str(persisted.execution_id)},
                )
            return self._backend(persisted)

    async def backend_context(self, execution_id: UUID) -> BackendExecutionContext:
        return self._backend(await self._load_snapshot(execution_id))

    async def voice_context(self, execution_id: UUID) -> VoiceExecutionContext:
        snapshot = await self._load_snapshot(execution_id)
        value = self._mapping(self._target(snapshot)["voice"])
        return VoiceExecutionContext(
            execution_id=execution_id,
            tenant=dict(self._mapping(value["tenant"])),
            agent=dict(self._mapping(value["agent"])),
            architecture=str(value["architecture"]),
            prompts=dict(self._mapping(value["prompts"])),
            runtime=dict(self._mapping(value["runtime"])),
            actions=[
                dict(self._mapping(item))
                for item in cast(list[object], value["actions"])
            ],
            handoff=[
                dict(self._mapping(item))
                for item in cast(list[object], value["handoff"])
            ],
        )

    async def worker_context(
        self, execution_id: UUID, action_key: str
    ) -> WorkerExecutionContext:
        snapshot = await self._load_snapshot(execution_id)
        actions = self._mapping(self._target(snapshot)["actions"])
        action = actions.get(action_key)
        if not isinstance(action, Mapping):
            raise ManagedResourceNotFound("execution action not found")
        integration = action.get("integration")
        return WorkerExecutionContext(
            execution_id=execution_id,
            tenant_id=snapshot.tenant_id,
            action=dict(action),
            integration=(
                dict(self._mapping(integration)) if integration is not None else None
            ),
        )

    async def runtime_secret(
        self, execution_id: UUID, slot: RuntimeSecretSlot
    ) -> RuntimeSecretMaterial:
        async with self._sessions.begin() as session:
            snapshot = await self._required_snapshot(session, execution_id)
            secret, _, _ = await self._active_secret(
                session,
                self._runtime_credential_id(snapshot, slot),
                snapshot.tenant_id,
            )
            return RuntimeSecretMaterial(slot=slot, secret=secret)

    async def integration_material(
        self, execution_id: UUID, integration_key: str
    ) -> IntegrationExecutionMaterial:
        async with self._sessions.begin() as session:
            snapshot = await self._required_snapshot(session, execution_id)
            bindings = self._mapping(self._target(snapshot)["bindings"])
            integrations = self._mapping(bindings["integrations"])
            raw_id = integrations.get(integration_key)
            if raw_id is None:
                raise ManagedResourceNotFound("execution integration not found")
            connection = await session.get(IntegrationConnection, UUID(str(raw_id)))
            self._validate_integration(snapshot, integration_key, connection)
            assert connection is not None
            config = self._integration_config(connection)
            secret = None
            if config.authentication.type == "none":
                if connection.credential_id is not None:
                    raise ManagedResourceConflict(
                        "HTTP no-auth connection has a credential"
                    )
            else:
                if connection.credential_id is None:
                    raise ManagedResourceConflict(
                        "HTTP API-key connection has no credential"
                    )
                secret, _, _ = await self._active_secret(
                    session, connection.credential_id, snapshot.tenant_id
                )
            return IntegrationExecutionMaterial(
                integration_kind=connection.integration_kind,
                config=config.model_dump(mode="json"),
                secret=secret,
            )

    async def handoff_material(
        self, execution_id: UUID, destination_key: str
    ) -> HandoffExecutionMaterial:
        async with self._sessions.begin() as session:
            snapshot = await self._required_snapshot(session, execution_id)
            bindings = self._mapping(self._target(snapshot)["bindings"])
            handoffs = self._mapping(bindings["handoff"])
            raw_id = handoffs.get(destination_key)
            if raw_id is None:
                raise ManagedResourceNotFound("execution handoff destination not found")
            destination = await session.get(HandoffDestination, UUID(str(raw_id)))
            if (
                destination is None
                or destination.tenant_id != snapshot.tenant_id
                or destination.key != destination_key
            ):
                raise ManagedResourceNotFound("execution handoff destination not found")
            if not destination.enabled:
                raise ManagedResourceConflict("handoff destination is not enabled")
            return HandoffExecutionMaterial(
                destination_key=destination_key,
                phone_number=destination.phone_number,
            )

    async def _load_snapshot(self, execution_id: UUID) -> ExecutionSnapshot:
        async with self._sessions() as session:
            return await self._required_snapshot(session, execution_id)

    async def _required_snapshot(
        self, session: AsyncSession, execution_id: UUID
    ) -> ExecutionSnapshot:
        snapshot = await self._snapshots.get_in_session(session, execution_id)
        if snapshot is None:
            raise ManagedResourceNotFound("execution not found")
        return snapshot

    @staticmethod
    def _target(snapshot: ExecutionSnapshot) -> Mapping[str, object]:
        return snapshot.target

    def _backend(self, snapshot: ExecutionSnapshot) -> BackendExecutionContext:
        value = self._mapping(self._target(snapshot)["backend"])
        return BackendExecutionContext(
            execution_id=snapshot.execution_id,
            tenant_id=snapshot.tenant_id,
            architecture=str(value["architecture"]),
            backend_actions=dict(self._mapping(value["backend_actions"])),
            handoff=[
                dict(self._mapping(item))
                for item in cast(list[object], value["handoff"])
            ],
            metadata=dict(self._mapping(value["metadata"])),
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise ManagedResourceConflict("execution snapshot state is invalid")
        return value

    def _target_state(
        self, resolution: ExecutionResolution, context: Mapping[str, object]
    ) -> dict[str, object]:
        actions = {str(action["key"]): action for action in resolution.actions}
        handoff = [
            {
                "destination_key": str(item["key"]),
                "description": item["description"],
            }
            for item in resolution.handoff
        ]
        runtime_actions = [
            action for action in actions.values() if action["phase"] == "runtime"
        ]
        post_call = [
            action for action in actions.values() if action["phase"] == "post_call"
        ]
        return {
            "backend": {
                "architecture": resolution.architecture,
                "backend_actions": {
                    "capabilities": runtime_actions,
                    "post_call": post_call,
                },
                "handoff": handoff,
                "metadata": dict(context),
            },
            "voice": {
                "tenant": {
                    "locale": resolution.agent.locale,
                    "timezone": resolution.agent.timezone,
                },
                "agent": {
                    "name": resolution.agent.display_name,
                    "personality": resolution.agent.agent_profile,
                    "greeting": resolution.agent.greeting,
                },
                "architecture": resolution.architecture,
                "prompts": {
                    "system": self._prompt_content(resolution.prompts["system"]),
                    "profile": self._prompt_content(resolution.prompts["profile"]),
                    "tenant": self._prompt_content(resolution.prompts["tenant"]),
                    "knowledge": self._prompt_content(resolution.knowledge),
                },
                "runtime": self._voice_runtime(resolution.runtime.selected),
                "actions": runtime_actions,
                "handoff": handoff,
            },
            "actions": actions,
            "bindings": {
                "runtime_secrets": self._runtime_bindings(resolution.runtime.selected),
                "integrations": {
                    str(key): str(value)
                    for key, value in resolution.integration_bindings.items()
                },
                "handoff": {
                    str(item["key"]): str(item["id"]) for item in resolution.handoff
                },
            },
        }

    @staticmethod
    def _prompt_content(value: object) -> str:
        assert isinstance(value, Mapping)
        return str(value["content"])

    @classmethod
    def _voice_runtime(cls, runtime: ResolvedRuntime) -> dict[str, object]:
        if isinstance(runtime, ResolvedCascadeRuntime):
            policy = runtime.execution.policy.model_dump(mode="json")
            return {
                "stt": {
                    **cls._without_deployment_ref(runtime.stt.defaults),
                    "language": runtime.stt.language,
                    "speech_hints": cls._plain(runtime.stt.speech_hints),
                    **cls._provider_semantics(runtime.stt.resource),
                    "speech_activity": policy["speech_activity"],
                    "commit": policy["stt_commit"],
                    "endpointing": policy["endpointing"],
                },
                "llm": {
                    **cls._without_deployment_ref(runtime.llm.parameters),
                    **cls._provider_semantics(runtime.llm.resource),
                    "interruption": policy["interruption"],
                    "response_scheduling": policy["response_scheduling"],
                },
                "tts": {
                    **cls._without_deployment_ref(runtime.tts.defaults),
                    "voice": runtime.tts.voice,
                    **cls._provider_semantics(runtime.tts.resource),
                    "tokenizer": policy["tokenizer"],
                },
                "realtime": None,
            }
        return {
            "stt": None,
            "llm": None,
            "tts": None,
            "realtime": {
                "model": cls._provider_semantics(runtime.model.resource),
                "input_transcription": {
                    "language": runtime.input_transcription.language,
                    "speech_hints": cls._plain(
                        runtime.input_transcription.speech_hints
                    ),
                    **cls._provider_semantics(runtime.input_transcription.resource),
                },
                "voice": runtime.voice,
                "turn_completion": cls._plain(runtime.turn_completion),
                "interruption": runtime.interruption.model_dump(mode="json"),
            },
        }

    @staticmethod
    def _provider_semantics(
        resource: ResolvedProviderResource,
    ) -> dict[str, object]:
        return {
            "provider_kind": resource.connection.provider_kind,
            "connection_config": dict(resource.connection.connection_config),
            "deployment_kind": resource.deployment.deployment_kind.value,
            "deployment_config": dict(resource.deployment.deployment_config),
        }

    @staticmethod
    def _without_deployment_ref(value: object) -> dict[str, object]:
        payload = cast(Any, value).model_dump(mode="json")
        payload.pop("deployment_ref", None)
        return cast(dict[str, object], payload)

    @staticmethod
    def _plain(value: object) -> object:
        from control_plane.domain.runtime_execution_snapshot import _json_value

        return _json_value(value)

    @staticmethod
    def _runtime_bindings(runtime: ResolvedRuntime) -> dict[str, str]:
        resources = (
            {
                RuntimeSecretSlot.LLM: runtime.llm.resource,
                RuntimeSecretSlot.STT: runtime.stt.resource,
                RuntimeSecretSlot.TTS: runtime.tts.resource,
            }
            if isinstance(runtime, ResolvedCascadeRuntime)
            else {
                RuntimeSecretSlot.MODEL: runtime.model.resource,
                RuntimeSecretSlot.INPUT_TRANSCRIPTION: runtime.input_transcription.resource,
            }
        )
        return {
            slot.value: str(resource.credential.credential_ref)
            for slot, resource in resources.items()
        }

    def _runtime_credential_id(
        self, snapshot: ExecutionSnapshot, slot: RuntimeSecretSlot
    ) -> UUID:
        bindings = self._mapping(self._target(snapshot)["bindings"])
        values = self._mapping(bindings["runtime_secrets"])
        value = values.get(slot.value)
        if value is None:
            raise InvalidManagedResource(
                "runtime secret slot is not valid for execution architecture"
            )
        return UUID(str(value))

    @staticmethod
    def _validate_integration(
        snapshot: ExecutionSnapshot,
        integration_key: str,
        connection: IntegrationConnection | None,
    ) -> None:
        if (
            connection is None
            or connection.tenant_id != snapshot.tenant_id
            or connection.key != integration_key
        ):
            raise ManagedResourceNotFound("execution integration not found")
        if connection.integration_kind != "http" or not connection.enabled:
            raise ManagedResourceConflict("integration connection is not enabled HTTP")

    @staticmethod
    def _integration_config(
        connection: IntegrationConnection,
    ) -> HttpConnectionConfiguration:
        try:
            return HttpConnectionConfiguration.model_validate(connection.config)
        except ValueError as error:
            raise InvalidManagedResource(
                "integration configuration is invalid"
            ) from error

    async def _active_secret(
        self,
        session: AsyncSession,
        credential_id: UUID,
        tenant_id: str | None = None,
    ) -> tuple[str, Credential, CredentialVersion]:
        if self._cipher is None:
            raise RuntimeError("secret materialization is not configured")
        credential = await session.get(Credential, credential_id)
        if credential is None or (
            credential.scope_type == "tenant" and credential.tenant_id != tenant_id
        ):
            raise ManagedResourceNotFound("credential not found")
        if credential.status != "active" or credential.active_version_id is None:
            raise ManagedResourceConflict("credential is not usable")
        version = await session.get(CredentialVersion, credential.active_version_id)
        if (
            version is None
            or version.credential_id != credential.id
            or version.retired_at is not None
        ):
            raise ManagedResourceConflict("credential has no active version")
        return (
            self._cipher.decrypt(
                credential.id,
                version.version_number,
                version.nonce,
                version.ciphertext,
                version.key_id,
                version.algorithm,
            ),
            credential,
            version,
        )
