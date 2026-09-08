from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.components import ComponentAddress
from control_plane.domain.live_components import LiveComponentState

from .models import LiveComponent as LiveComponentRow


class SqlAlchemyLiveComponentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, address: ComponentAddress, *, lock: bool = False):
        statement = select(LiveComponentRow).where(
            LiveComponentRow.kind == str(address.kind),
            LiveComponentRow.scope_type == address.scope.type.value,
            LiveComponentRow.scope_key.is_(None)
            if address.scope.key is None
            else LiveComponentRow.scope_key == address.scope.key,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        return self._state(address, row) if row else None

    async def set(
        self,
        address: ComponentAddress,
        value: Mapping[str, object],
        schema_version: int,
        actor: str,
    ):
        row = await self._session.scalar(
            select(LiveComponentRow)
            .where(
                LiveComponentRow.kind == str(address.kind),
                LiveComponentRow.scope_type == address.scope.type.value,
                LiveComponentRow.scope_key.is_(None)
                if address.scope.key is None
                else LiveComponentRow.scope_key == address.scope.key,
            )
            .with_for_update()
        )
        if row is None:
            row = LiveComponentRow(
                kind=str(address.kind),
                scope_type=address.scope.type.value,
                scope_key=address.scope.key,
                value=dict(value),
                schema_version=schema_version,
                generation=1,
                updated_by=actor,
            )
            self._session.add(row)
        else:
            row.value = dict(value)
            row.schema_version = schema_version
            row.generation += 1
            row.updated_at = func.now()
            row.updated_by = actor
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise RuntimeError("live component address conflict") from error
        await self._session.refresh(row)
        return self._state(address, row)

    @staticmethod
    def _state(address, row):
        return LiveComponentState(
            address,
            dict(row.value),
            row.schema_version,
            row.generation,
            row.updated_at,
            row.updated_by,
        )
