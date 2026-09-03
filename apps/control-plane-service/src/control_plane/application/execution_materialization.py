from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.runtime_execution_snapshot import ExecutionSnapshot
from control_plane.domain.runtime_resolution import (
    ResolvedCascadeRuntime,
    ResolvedProviderResource,
)
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.models import (
    Credential,
    CredentialVersion,
    IntegrationConnection,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)


class RuntimeSecretSlot(StrEnum):
    LLM = "llm"
    STT = "stt"
    TTS = "tts"
    MODEL = "model"
    INPUT_TRANSCRIPTION = "input_transcription"


@dataclass(frozen=True, slots=True)
class RuntimeSecretMaterial:
    snapshot_id: UUID
    slot: RuntimeSecretSlot
    secret: str
    credential_ref: UUID
    credential_generation: int
    credential_version_id: UUID
    credential_version_number: int
    provider_connection_ref: UUID
    provider_connection_generation: int
    model_deployment_ref: UUID
    model_deployment_generation: int

    def __repr__(self) -> str:
        return f"RuntimeSecretMaterial(snapshot_id={self.snapshot_id!r}, slot={self.slot!r}, credential_ref={self.credential_ref!r})"


@dataclass(frozen=True, slots=True)
class IntegrationExecutionMaterial:
    tenant_id: str
    integration_connection_id: UUID
    integration_connection_generation: int
    integration_kind: str
    config: dict[str, object]
    secret: str | None
    credential_ref: UUID | None
    credential_generation: int | None
    credential_version_id: UUID | None
    credential_version_number: int | None

    def __repr__(self) -> str:
        return f"IntegrationExecutionMaterial(tenant_id={self.tenant_id!r}, integration_connection_id={self.integration_connection_id!r})"


class ExecutionMaterializationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: CredentialCipher,
        snapshots: SqlAlchemyExecutionSnapshotRepository,
    ) -> None:
        self._sessions, self._cipher, self._snapshots = sessions, cipher, snapshots

    async def runtime_secret(
        self, snapshot_id: UUID, slot: RuntimeSecretSlot
    ) -> RuntimeSecretMaterial:
        async with self._sessions.begin() as session:
            snapshot = await self._snapshots.get_in_session(session, snapshot_id)
            if snapshot is None:
                raise ManagedResourceNotFound("runtime execution snapshot not found")
            resource = self._runtime_resource(snapshot, slot)
            # Snapshot provenance is authoritative; reject a corrupt/tampered duplicate.
            if (
                resource.connection.credential_ref.value
                != resource.credential.credential_ref
            ):
                raise ManagedResourceConflict(
                    "snapshot credential provenance is inconsistent"
                )
            secret, credential, version = await self._active_secret(
                session, resource.credential.credential_ref
            )
            return RuntimeSecretMaterial(
                snapshot_id,
                slot,
                secret,
                credential.id,
                credential.generation,
                version.id,
                version.version_number,
                resource.connection.ref.value,
                resource.connection.generation,
                resource.deployment.ref.value,
                resource.deployment.generation,
            )

    async def integration_material(
        self, tenant_id: str, connection_id: UUID
    ) -> IntegrationExecutionMaterial:
        async with self._sessions.begin() as session:
            connection = await session.get(IntegrationConnection, connection_id)
            if connection is None or connection.tenant_id != tenant_id:
                raise ManagedResourceNotFound("integration connection not found")
            if connection.integration_kind != "http" or not connection.enabled:
                raise ManagedResourceConflict(
                    "integration connection is not enabled HTTP"
                )
            from contracts.integration import HttpConnectionConfiguration

            try:
                config = HttpConnectionConfiguration.model_validate(connection.config)
            except ValueError as error:
                raise InvalidManagedResource(
                    "integration configuration is invalid"
                ) from error
            if config.authentication.type == "none":
                if connection.credential_id is not None:
                    raise ManagedResourceConflict(
                        "HTTP no-auth connection has a credential"
                    )
                return IntegrationExecutionMaterial(
                    tenant_id,
                    connection.id,
                    connection.generation,
                    "http",
                    config.model_dump(mode="json"),
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            if connection.credential_id is None:
                raise ManagedResourceConflict(
                    "HTTP API-key connection has no credential"
                )
            secret, credential, version = await self._active_secret(
                session, connection.credential_id
            )
            return IntegrationExecutionMaterial(
                tenant_id,
                connection.id,
                connection.generation,
                "http",
                config.model_dump(mode="json"),
                secret,
                credential.id,
                credential.generation,
                version.id,
                version.version_number,
            )

    def _runtime_resource(
        self, snapshot: ExecutionSnapshot, slot: RuntimeSecretSlot
    ) -> ResolvedProviderResource:
        runtime = snapshot.runtime
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
        resource = resources.get(slot)
        if resource is None:
            raise InvalidManagedResource(
                "runtime secret slot is not valid for snapshot architecture"
            )
        return resource

    async def _active_secret(
        self, session: AsyncSession, credential_id: UUID
    ) -> tuple[str, Credential, CredentialVersion]:
        credential = await session.get(Credential, credential_id)
        if credential is None:
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
