from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from contracts import (
    MANAGED_RESOURCE_CHANGED_EVENT_TYPE,
    MANAGED_RESOURCE_CHANGED_SUBJECT,
    ManagedResourceChangedPayloadV1,
    ManagedResourceChangedV1,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialStatus,
    CredentialVersion,
    DeploymentKind,
    HandoffDestination,
    HandoffDestinationRef,
    IntegrationConnection,
    IntegrationConnectionRef,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.infrastructure.encryption import CredentialCipher

from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import HandoffDestination as HandoffDestinationRow
from .models import IntegrationConnection as IntegrationConnectionRow
from .models import ModelDeployment as ModelDeploymentRow
from .models import OutboxMessage
from .models import PhoneNumberAssignment as PhoneNumberAssignmentRow
from .models import ProviderConnection as ProviderConnectionRow


class SqlAlchemyManagedResourceRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: CredentialCipher,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions.begin() as session:
                yield session
        except IntegrityError as error:
            raise ManagedResourceConflict(
                "managed resource constraint conflict"
            ) from error

    async def create_credential(self, name: str, secret: str, actor: str) -> Credential:
        async with self._transaction() as session:
            row = CredentialRow(name=name, status="active", created_by=actor)
            session.add(row)
            await session.flush()
            nonce, ciphertext = self._cipher.encrypt(row.id, 1, secret)
            version = CredentialVersionRow(
                credential_id=row.id,
                version_number=1,
                key_id=self._cipher.key_id,
                algorithm=self._cipher.ALGORITHM,
                nonce=nonce,
                ciphertext=ciphertext,
                created_by=actor,
            )
            session.add(version)
            await session.flush()
            row.active_version_id = version.id
            self._event(
                session, "credential", row.id, "created", row.generation, row.status
            )
            await session.flush()
            await session.refresh(row)
            return self._credential(row, 1)

    async def rotate_credential(
        self, credential_ref: CredentialRef, secret: str, actor: str
    ) -> Credential:
        async with self._transaction() as session:
            row = await self._credential_row(session, credential_ref, lock=True)
            if row.status == CredentialStatus.REVOKED:
                raise ManagedResourceConflict("revoked credential cannot be rotated")
            active = await session.get(
                CredentialVersionRow, row.active_version_id, with_for_update=True
            )
            if active is None:
                raise ManagedResourceConflict("credential has no active version")
            active.retired_at = func.now()
            number = active.version_number + 1
            nonce, ciphertext = self._cipher.encrypt(row.id, number, secret)
            version = CredentialVersionRow(
                credential_id=row.id,
                version_number=number,
                key_id=self._cipher.key_id,
                algorithm=self._cipher.ALGORITHM,
                nonce=nonce,
                ciphertext=ciphertext,
                created_by=actor,
            )
            session.add(version)
            await session.flush()
            row.active_version_id = version.id
            row.generation += 1
            self._event(
                session, "credential", row.id, "rotated", row.generation, row.status
            )
            await session.flush()
            await session.refresh(row)
            return self._credential(row, number)

    async def revoke_credential(
        self, credential_ref: CredentialRef, actor: str
    ) -> Credential:
        async with self._transaction() as session:
            row = await self._credential_row(session, credential_ref, lock=True)
            if row.status == CredentialStatus.REVOKED:
                raise ManagedResourceConflict("credential is already revoked")
            row.status = CredentialStatus.REVOKED
            row.revoked_at = func.now()
            row.revoked_by = actor
            active = await session.get(
                CredentialVersionRow, row.active_version_id, with_for_update=True
            )
            if active is not None:
                active.retired_at = func.now()
            row.active_version_id = None
            row.generation += 1
            self._event(
                session, "credential", row.id, "revoked", row.generation, row.status
            )
            await session.flush()
            await session.refresh(row)
            return self._credential(row, None)

    async def get_credential(self, credential_ref: CredentialRef) -> Credential:
        async with self._sessions() as session:
            row = await self._credential_row(session, credential_ref)
            number = await self._active_version_number(session, row)
            return self._credential(row, number)

    async def list_credentials(self) -> Sequence[Credential]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(CredentialRow).order_by(CredentialRow.name)
                )
            ).all()
            return [
                self._credential(row, await self._active_version_number(session, row))
                for row in rows
            ]

    async def list_credential_versions(
        self, credential_ref: CredentialRef
    ) -> Sequence[CredentialVersion]:
        async with self._sessions() as session:
            await self._credential_row(session, credential_ref)
            rows = (
                await session.scalars(
                    select(CredentialVersionRow)
                    .where(CredentialVersionRow.credential_id == credential_ref.value)
                    .order_by(CredentialVersionRow.version_number)
                )
            ).all()
            return [
                CredentialVersion(
                    row.id,
                    credential_ref,
                    row.version_number,
                    row.created_at,
                    row.created_by,
                    row.retired_at,
                )
                for row in rows
            ]

    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        config: dict[str, object],
        enabled: bool,
        actor: str,
    ) -> ProviderConnection:
        async with self._transaction() as session:
            credential = await self._credential_row(session, credential_ref, lock=True)
            self._require_usable_credential(credential, enabled)
            row = ProviderConnectionRow(
                key=key,
                provider_kind=provider_kind,
                credential_id=credential_ref.value,
                connection_config=config,
                enabled=enabled,
                generation=1,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            await session.flush()
            self._event(
                session, "provider_connection", row.id, "created", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._connection(row)

    async def update_connection(
        self,
        connection_ref: ProviderConnectionRef,
        credential_ref: CredentialRef,
        config: dict[str, object],
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection:
        async with self._transaction() as session:
            row = await self._connection_row(session, connection_ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            credential = await self._credential_row(session, credential_ref, lock=True)
            self._require_usable_credential(credential, row.enabled)
            row.credential_id = credential_ref.value
            row.connection_config = config
            row.generation += 1
            row.updated_at = func.now()
            row.updated_by = actor
            self._event(
                session, "provider_connection", row.id, "updated", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._connection(row)

    async def set_connection_enabled(
        self,
        connection_ref: ProviderConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection:
        async with self._transaction() as session:
            row = await self._connection_row(session, connection_ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if row.enabled == enabled:
                raise ManagedResourceConflict(
                    f"provider connection is already {'enabled' if enabled else 'disabled'}"
                )
            credential = await self._credential_row(
                session, CredentialRef(row.credential_id), lock=True
            )
            self._require_usable_credential(credential, enabled)
            row.enabled = enabled
            row.generation += 1
            row.updated_at = func.now()
            row.updated_by = actor
            self._event(
                session,
                "provider_connection",
                row.id,
                "enabled" if enabled else "disabled",
                row.generation,
            )
            await session.flush()
            await session.refresh(row)
            return self._connection(row)

    async def get_connection(
        self, connection_ref: ProviderConnectionRef
    ) -> ProviderConnection:
        async with self._sessions() as session:
            return self._connection(await self._connection_row(session, connection_ref))

    async def list_connections(self) -> Sequence[ProviderConnection]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ProviderConnectionRow).order_by(ProviderConnectionRow.key)
                )
            ).all()
            return [self._connection(row) for row in rows]

    async def create_integration_connection(
        self,
        tenant_id: str,
        key: str,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        enabled: bool,
        actor: str,
    ) -> IntegrationConnection:
        async with self._transaction() as session:
            if credential_ref is not None:
                self._require_usable_credential(
                    await self._credential_row(session, credential_ref, lock=enabled),
                    enabled,
                )
            row = IntegrationConnectionRow(
                tenant_id=tenant_id,
                key=key,
                integration_kind="http",
                config=config,
                credential_id=credential_ref.value if credential_ref else None,
                enabled=enabled,
                generation=1,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            await session.flush()
            self._event(
                session, "integration_connection", row.id, "created", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._integration_connection(row)

    async def update_integration_connection(
        self,
        ref: IntegrationConnectionRef,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection:
        async with self._transaction() as session:
            row = await self._integration_connection_row(session, ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if credential_ref is not None:
                self._require_usable_credential(
                    await self._credential_row(
                        session, credential_ref, lock=row.enabled
                    ),
                    row.enabled,
                )
            row.config, row.credential_id = (
                config,
                credential_ref.value if credential_ref else None,
            )
            row.generation += 1
            row.updated_at, row.updated_by = func.now(), actor
            self._event(
                session, "integration_connection", row.id, "updated", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._integration_connection(row)

    async def set_integration_connection_enabled(
        self,
        ref: IntegrationConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection:
        async with self._transaction() as session:
            row = await self._integration_connection_row(session, ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if row.enabled == enabled:
                raise ManagedResourceConflict(
                    f"integration connection is already {'enabled' if enabled else 'disabled'}"
                )
            if enabled and row.credential_id is not None:
                self._require_usable_credential(
                    await self._credential_row(
                        session, CredentialRef(row.credential_id), lock=True
                    ),
                    True,
                )
            row.enabled, row.generation = enabled, row.generation + 1
            row.updated_at, row.updated_by = func.now(), actor
            self._event(
                session,
                "integration_connection",
                row.id,
                "enabled" if enabled else "disabled",
                row.generation,
            )
            await session.flush()
            await session.refresh(row)
            return self._integration_connection(row)

    async def get_integration_connection(
        self, ref: IntegrationConnectionRef
    ) -> IntegrationConnection:
        async with self._sessions() as session:
            return self._integration_connection(
                await self._integration_connection_row(session, ref)
            )

    async def list_integration_connections(
        self, tenant_id: str | None = None
    ) -> Sequence[IntegrationConnection]:
        async with self._sessions() as session:
            statement = select(IntegrationConnectionRow).order_by(
                IntegrationConnectionRow.tenant_id, IntegrationConnectionRow.key
            )
            if tenant_id is not None:
                statement = statement.where(
                    IntegrationConnectionRow.tenant_id == tenant_id
                )
            return [
                self._integration_connection(row)
                for row in (await session.scalars(statement)).all()
            ]

    async def create_handoff_destination(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        enabled: bool,
        actor: str,
    ) -> HandoffDestination:
        async with self._transaction() as session:
            row = HandoffDestinationRow(
                tenant_id=tenant_id,
                key=key,
                description=description,
                phone_number=phone_number,
                enabled=enabled,
                generation=1,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            await session.flush()
            self._event(
                session, "handoff_destination", row.id, "created", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._handoff_destination(row)

    async def update_handoff_destination(
        self,
        ref: HandoffDestinationRef,
        description: str,
        phone_number: str,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination:
        async with self._transaction() as session:
            row = await self._handoff_destination_row(session, ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            row.description, row.phone_number = description, phone_number
            row.generation += 1
            row.updated_at, row.updated_by = func.now(), actor
            self._event(
                session, "handoff_destination", row.id, "updated", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._handoff_destination(row)

    async def set_handoff_destination_enabled(
        self,
        ref: HandoffDestinationRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination:
        async with self._transaction() as session:
            row = await self._handoff_destination_row(session, ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if row.enabled == enabled:
                raise ManagedResourceConflict(
                    f"handoff destination is already {'enabled' if enabled else 'disabled'}"
                )
            row.enabled, row.generation = enabled, row.generation + 1
            row.updated_at, row.updated_by = func.now(), actor
            self._event(
                session,
                "handoff_destination",
                row.id,
                "enabled" if enabled else "disabled",
                row.generation,
            )
            await session.flush()
            await session.refresh(row)
            return self._handoff_destination(row)

    async def get_handoff_destination(
        self, ref: HandoffDestinationRef
    ) -> HandoffDestination:
        async with self._sessions() as session:
            return self._handoff_destination(
                await self._handoff_destination_row(session, ref)
            )

    async def list_handoff_destinations(
        self, tenant_id: str | None = None
    ) -> Sequence[HandoffDestination]:
        async with self._sessions() as session:
            statement = select(HandoffDestinationRow).order_by(
                HandoffDestinationRow.tenant_id, HandoffDestinationRow.key
            )
            if tenant_id is not None:
                statement = statement.where(
                    HandoffDestinationRow.tenant_id == tenant_id
                )
            return [
                self._handoff_destination(row)
                for row in (await session.scalars(statement)).all()
            ]

    async def create_phone_number_assignment(
        self, tenant_id: str, phone_number: str, enabled: bool, actor: str
    ) -> PhoneNumberAssignment:
        async with self._transaction() as session:
            row = PhoneNumberAssignmentRow(
                tenant_id=tenant_id,
                phone_number=phone_number,
                enabled=enabled,
                generation=1,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            await session.flush()
            self._event(
                session, "phone_number_assignment", row.id, "created", row.generation
            )
            await session.flush()
            await session.refresh(row)
            return self._phone_number_assignment(row)

    async def set_phone_number_assignment_enabled(
        self,
        ref: PhoneNumberAssignmentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> PhoneNumberAssignment:
        async with self._transaction() as session:
            row = await self._phone_number_assignment_row(session, ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if row.enabled == enabled:
                raise ManagedResourceConflict(
                    f"phone number assignment is already {'enabled' if enabled else 'disabled'}"
                )
            row.enabled, row.generation = enabled, row.generation + 1
            row.updated_at, row.updated_by = func.now(), actor
            self._event(
                session,
                "phone_number_assignment",
                row.id,
                "enabled" if enabled else "disabled",
                row.generation,
            )
            await session.flush()
            await session.refresh(row)
            return self._phone_number_assignment(row)

    async def get_phone_number_assignment(
        self, ref: PhoneNumberAssignmentRef
    ) -> PhoneNumberAssignment:
        async with self._sessions() as session:
            return self._phone_number_assignment(
                await self._phone_number_assignment_row(session, ref)
            )

    async def list_phone_number_assignments(
        self, tenant_id: str | None = None
    ) -> Sequence[PhoneNumberAssignment]:
        async with self._sessions() as session:
            statement = select(PhoneNumberAssignmentRow).order_by(
                PhoneNumberAssignmentRow.tenant_id,
                PhoneNumberAssignmentRow.phone_number,
            )
            if tenant_id is not None:
                statement = statement.where(
                    PhoneNumberAssignmentRow.tenant_id == tenant_id
                )
            return [
                self._phone_number_assignment(row)
                for row in (await session.scalars(statement)).all()
            ]

    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        kind: DeploymentKind,
        config: dict[str, object],
        enabled: bool,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment:
        async with self._transaction() as session:
            connection = await self._connection_row(session, connection_ref, lock=True)
            await self._require_usable_connection(session, connection, enabled)
            row = ModelDeploymentRow(
                key=key,
                connection_id=connection_ref.value,
                deployment_kind=kind.value,
                deployment_config=config,
                llm_capabilities=(
                    {
                        "supports_temperature": llm_capabilities.supports_temperature,
                        "supports_reasoning_effort": llm_capabilities.supports_reasoning_effort,
                    }
                    if llm_capabilities
                    else None
                ),
                realtime_capabilities=(
                    {
                        "supports_server_vad": realtime_capabilities.supports_server_vad,
                        "supports_semantic_vad": realtime_capabilities.supports_semantic_vad,
                    }
                    if realtime_capabilities
                    else None
                ),
                stt_capabilities=(
                    {
                        "supports_cascade": stt_capabilities.supports_cascade,
                        "supports_realtime_input_transcription": stt_capabilities.supports_realtime_input_transcription,
                    }
                    if stt_capabilities
                    else None
                ),
                enabled=enabled,
                generation=1,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            await session.flush()
            self._event(session, "model_deployment", row.id, "created", row.generation)
            await session.flush()
            await session.refresh(row)
            return self._deployment(row)

    async def update_deployment(
        self,
        deployment_ref: ModelDeploymentRef,
        connection_ref: ProviderConnectionRef,
        config: dict[str, object],
        expected_generation: int,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment:
        async with self._transaction() as session:
            row = await self._deployment_row(session, deployment_ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            connection = await self._connection_row(session, connection_ref, lock=True)
            await self._require_usable_connection(session, connection, row.enabled)
            row.connection_id = connection_ref.value
            row.deployment_config = config
            row.llm_capabilities = (
                {
                    "supports_temperature": llm_capabilities.supports_temperature,
                    "supports_reasoning_effort": llm_capabilities.supports_reasoning_effort,
                }
                if llm_capabilities
                else None
            )
            row.realtime_capabilities = (
                {
                    "supports_server_vad": realtime_capabilities.supports_server_vad,
                    "supports_semantic_vad": realtime_capabilities.supports_semantic_vad,
                }
                if realtime_capabilities
                else None
            )
            row.stt_capabilities = (
                {
                    "supports_cascade": stt_capabilities.supports_cascade,
                    "supports_realtime_input_transcription": stt_capabilities.supports_realtime_input_transcription,
                }
                if stt_capabilities
                else None
            )
            row.generation += 1
            row.updated_at = func.now()
            row.updated_by = actor
            self._event(session, "model_deployment", row.id, "updated", row.generation)
            await session.flush()
            await session.refresh(row)
            return self._deployment(row)

    async def set_deployment_enabled(
        self,
        deployment_ref: ModelDeploymentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ModelDeployment:
        async with self._transaction() as session:
            row = await self._deployment_row(session, deployment_ref, lock=True)
            self._check_generation(row.generation, expected_generation)
            if row.enabled == enabled:
                raise ManagedResourceConflict(
                    f"model deployment is already {'enabled' if enabled else 'disabled'}"
                )
            connection = await self._connection_row(
                session, ProviderConnectionRef(row.connection_id), lock=True
            )
            await self._require_usable_connection(session, connection, enabled)
            row.enabled = enabled
            row.generation += 1
            row.updated_at = func.now()
            row.updated_by = actor
            self._event(
                session,
                "model_deployment",
                row.id,
                "enabled" if enabled else "disabled",
                row.generation,
            )
            await session.flush()
            await session.refresh(row)
            return self._deployment(row)

    async def get_deployment(
        self, deployment_ref: ModelDeploymentRef
    ) -> ModelDeployment:
        async with self._sessions() as session:
            return self._deployment(await self._deployment_row(session, deployment_ref))

    async def list_deployments(self) -> Sequence[ModelDeployment]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ModelDeploymentRow).order_by(ModelDeploymentRow.key)
                )
            ).all()
            return [self._deployment(row) for row in rows]

    async def _credential_row(
        self, session: AsyncSession, ref: CredentialRef, lock: bool = False
    ) -> CredentialRow:
        row = await session.get(CredentialRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
        return row

    async def _connection_row(
        self, session: AsyncSession, ref: ProviderConnectionRef, lock: bool = False
    ) -> ProviderConnectionRow:
        row = await session.get(ProviderConnectionRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"provider connection {ref.value} not found")
        return row

    async def _deployment_row(
        self, session: AsyncSession, ref: ModelDeploymentRef, lock: bool = False
    ) -> ModelDeploymentRow:
        row = await session.get(ModelDeploymentRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"model deployment {ref.value} not found")
        return row

    async def _integration_connection_row(
        self, session: AsyncSession, ref: IntegrationConnectionRef, lock: bool = False
    ) -> IntegrationConnectionRow:
        row = await session.get(
            IntegrationConnectionRow, ref.value, with_for_update=lock
        )
        if row is None:
            raise ManagedResourceNotFound(
                f"integration connection {ref.value} not found"
            )
        return row

    async def _handoff_destination_row(
        self, session: AsyncSession, ref: HandoffDestinationRef, lock: bool = False
    ) -> HandoffDestinationRow:
        row = await session.get(HandoffDestinationRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"handoff destination {ref.value} not found")
        return row

    async def _phone_number_assignment_row(
        self, session: AsyncSession, ref: PhoneNumberAssignmentRef, lock: bool = False
    ) -> PhoneNumberAssignmentRow:
        row = await session.get(
            PhoneNumberAssignmentRow, ref.value, with_for_update=lock
        )
        if row is None:
            raise ManagedResourceNotFound(
                f"phone number assignment {ref.value} not found"
            )
        return row

    async def _require_usable_connection(
        self, session: AsyncSession, row: ProviderConnectionRow, required: bool
    ) -> None:
        if required and not row.enabled:
            raise InvalidManagedResource(
                "enabled deployment requires enabled connection"
            )
        credential = await self._credential_row(
            session, CredentialRef(row.credential_id), lock=required
        )
        self._require_usable_credential(credential, required)

    @staticmethod
    def _require_usable_credential(row: CredentialRow, required: bool) -> None:
        if required and row.status == CredentialStatus.REVOKED:
            raise InvalidManagedResource("enabled resource requires active credential")

    @staticmethod
    def _check_generation(current: int, expected: int) -> None:
        if current != expected:
            raise ManagedResourceConflict(
                f"expected generation {expected}, current {current}"
            )

    @staticmethod
    async def _active_version_number(
        session: AsyncSession, row: CredentialRow
    ) -> int | None:
        if row.active_version_id is None:
            return None
        return await session.scalar(
            select(CredentialVersionRow.version_number).where(
                CredentialVersionRow.id == row.active_version_id
            )
        )

    @staticmethod
    def _event(
        session: AsyncSession,
        resource_type: Literal[
            "credential",
            "provider_connection",
            "model_deployment",
            "integration_connection",
            "handoff_destination",
            "phone_number_assignment",
        ],
        resource_id: UUID,
        action: Literal[
            "created", "updated", "enabled", "disabled", "rotated", "revoked"
        ],
        generation: int,
        status: str | None = None,
    ) -> None:
        event_id = uuid4()
        occurred_at = datetime.now(UTC)
        event = ManagedResourceChangedV1(
            event_id=event_id,
            occurred_at=occurred_at,
            payload=ManagedResourceChangedPayloadV1(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                resource_generation=generation,
                status=status,
            ),
        )
        session.add(
            OutboxMessage(
                id=event_id,
                event_type=MANAGED_RESOURCE_CHANGED_EVENT_TYPE,
                subject=MANAGED_RESOURCE_CHANGED_SUBJECT,
                payload=event.model_dump(mode="json"),
                component_id=None,
                revision_number=None,
                ordering_key=f"managed:{resource_type}:{resource_id}",
                ordering_sequence=generation,
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _credential(row: CredentialRow, number: int | None) -> Credential:
        return Credential(
            CredentialRef(row.id),
            row.name,
            row.active_version_id,
            number,
            CredentialStatus(row.status),
            row.generation,
            row.created_at,
            row.created_by,
            row.revoked_at,
            row.revoked_by,
        )

    @staticmethod
    def _connection(row: ProviderConnectionRow) -> ProviderConnection:
        return ProviderConnection(
            ProviderConnectionRef(row.id),
            row.key,
            row.provider_kind,
            CredentialRef(row.credential_id),
            dict(row.connection_config),
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _integration_connection(row: IntegrationConnectionRow) -> IntegrationConnection:
        return IntegrationConnection(
            IntegrationConnectionRef(row.id),
            row.tenant_id,
            row.key,
            row.integration_kind,
            dict(row.config),
            CredentialRef(row.credential_id) if row.credential_id else None,
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _handoff_destination(row: HandoffDestinationRow) -> HandoffDestination:
        return HandoffDestination(
            HandoffDestinationRef(row.id),
            row.tenant_id,
            row.key,
            row.description,
            row.phone_number,
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _phone_number_assignment(
        row: PhoneNumberAssignmentRow,
    ) -> PhoneNumberAssignment:
        return PhoneNumberAssignment(
            PhoneNumberAssignmentRef(row.id),
            row.tenant_id,
            row.phone_number,
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _deployment(row: ModelDeploymentRow) -> ModelDeployment:
        return ModelDeployment(
            ModelDeploymentRef(row.id),
            row.key,
            ProviderConnectionRef(row.connection_id),
            DeploymentKind(row.deployment_kind),
            dict(row.deployment_config),
            (
                LLMCapabilities(**row.llm_capabilities)
                if row.llm_capabilities is not None
                else None
            ),
            RealtimeCapabilities(**row.realtime_capabilities)
            if row.realtime_capabilities
            else None,
            STTCapabilities(**row.stt_capabilities) if row.stt_capabilities else None,
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )
