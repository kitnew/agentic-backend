from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    CredentialRef,
    CredentialStatus,
    CredentialVersion,
    HandoffDestination,
    HandoffDestinationRef,
    IntegrationConnection,
    IntegrationConnectionRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
)

from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import HandoffDestination as HandoffDestinationRow
from .models import IntegrationConnection as IntegrationConnectionRow
from .models import PhoneNumberAssignment as PhoneNumberAssignmentRow


class SqlAlchemyManagedResourceRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions.begin() as session:
                yield session
        except IntegrityError as error:
            raise ManagedResourceConflict(
                "managed resource constraint conflict"
            ) from error

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

    async def _credential_row(
        self, session: AsyncSession, ref: CredentialRef, lock: bool = False
    ) -> CredentialRow:
        row = await session.get(CredentialRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
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

    @staticmethod
    def _check_generation(current: int, expected: int) -> None:
        if current != expected:
            raise ManagedResourceConflict(
                f"expected generation {expected}, current {current}"
            )

    @staticmethod
    def _require_usable_credential(row: CredentialRow, required: bool) -> None:
        if required and row.status == CredentialStatus.REVOKED:
            raise InvalidManagedResource("enabled resource requires active credential")

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
