from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.managed_resource_errors import (
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    HandoffDestination,
    HandoffDestinationRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
)

from .models import HandoffDestination as HandoffRow
from .models import PhoneNumberAssignment as AssignmentRow


class SqlAlchemyPhoneNumberAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, tenant_id: str, phone_number: str, actor: str
    ) -> PhoneNumberAssignment:
        row = AssignmentRow(
            tenant_id=tenant_id,
            phone_number=phone_number,
            enabled=False,
            generation=1,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def set_enabled(
        self, assignment: PhoneNumberAssignment, enabled: bool, actor: str
    ) -> PhoneNumberAssignment:
        row = await self._row(assignment.ref)
        row.enabled = enabled
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def get(
        self, ref: PhoneNumberAssignmentRef, *, lock: bool = False
    ) -> PhoneNumberAssignment:
        return self._value(await self._row(ref, lock=lock))

    async def list(self, tenant_id: str) -> Sequence[PhoneNumberAssignment]:
        rows = (
            await self._session.scalars(
                select(AssignmentRow)
                .where(AssignmentRow.tenant_id == tenant_id)
                .order_by(AssignmentRow.phone_number, AssignmentRow.id)
            )
        ).all()
        return [self._value(row) for row in rows]

    async def resolve(self, phone_number: str) -> PhoneNumberAssignment:
        row = await self._session.scalar(
            select(AssignmentRow).where(
                AssignmentRow.phone_number == phone_number,
                AssignmentRow.enabled.is_(True),
            )
        )
        if row is None:
            raise ManagedResourceNotFound("inbound route not found")
        return self._value(row)

    async def _row(
        self, ref: PhoneNumberAssignmentRef, *, lock: bool = False
    ) -> AssignmentRow:
        row = await self._session.get(AssignmentRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(
                f"phone number assignment {ref.value} not found"
            )
        return row

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ManagedResourceConflict(
                "managed resource constraint conflict"
            ) from error

    @staticmethod
    def _value(row: AssignmentRow) -> PhoneNumberAssignment:
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


class SqlAlchemyHandoffDestinationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        actor: str,
    ) -> HandoffDestination:
        row = HandoffRow(
            tenant_id=tenant_id,
            key=key,
            description=description,
            phone_number=phone_number,
            enabled=False,
            generation=1,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def update(
        self,
        destination: HandoffDestination,
        description: str,
        phone_number: str,
        actor: str,
    ) -> HandoffDestination:
        row = await self._row(destination.ref)
        row.description = description
        row.phone_number = phone_number
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def set_enabled(
        self, destination: HandoffDestination, enabled: bool, actor: str
    ) -> HandoffDestination:
        row = await self._row(destination.ref)
        row.enabled = enabled
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def get(
        self, ref: HandoffDestinationRef, *, lock: bool = False
    ) -> HandoffDestination:
        return self._value(await self._row(ref, lock=lock))

    async def list(self, tenant_id: str) -> Sequence[HandoffDestination]:
        rows = (
            await self._session.scalars(
                select(HandoffRow)
                .where(HandoffRow.tenant_id == tenant_id)
                .order_by(HandoffRow.key)
            )
        ).all()
        return [self._value(row) for row in rows]

    async def _row(
        self, ref: HandoffDestinationRef, *, lock: bool = False
    ) -> HandoffRow:
        row = await self._session.get(HandoffRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"handoff destination {ref.value} not found")
        return row

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ManagedResourceConflict(
                "managed resource constraint conflict"
            ) from error

    @staticmethod
    def _value(row: HandoffRow) -> HandoffDestination:
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
