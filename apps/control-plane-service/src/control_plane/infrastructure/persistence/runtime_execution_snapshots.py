from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.domain.runtime_execution_snapshot import (
    RuntimeExecutionSnapshot,
    snapshot_from_payload,
)

from .models import RuntimeExecutionSnapshot as SnapshotRow


class SqlAlchemyRuntimeExecutionSnapshotRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self, session: AsyncSession, snapshot: RuntimeExecutionSnapshot, payload: dict[str, object]
    ) -> RuntimeExecutionSnapshot:
        session.add(
            SnapshotRow(
                snapshot_id=snapshot.snapshot_id,
                tenant_id=snapshot.tenant_id,
                schema_version=snapshot.schema_version,
                architecture=snapshot.architecture,
                payload=payload,
                content_hash=snapshot.content_hash,
                created_at=snapshot.created_at,
            )
        )
        return snapshot

    async def get(self, snapshot_id: UUID) -> RuntimeExecutionSnapshot | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id)
            )
            return self._snapshot(row) if row else None

    @staticmethod
    def _snapshot(row: SnapshotRow) -> RuntimeExecutionSnapshot:
        return snapshot_from_payload(
            row.snapshot_id, row.created_at, row.payload, row.content_hash
        )
