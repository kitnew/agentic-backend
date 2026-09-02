from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.runtime_resolver import (
    RuntimeResolutionReader,
    RuntimeResolver,
)
from control_plane.domain.runtime_execution_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    RuntimeExecutionSnapshot,
    content_hash,
    snapshot_payload,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyRuntimeExecutionSnapshotRepository,
)


class RuntimeMaterializationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        resolver: RuntimeResolver,
        reader: RuntimeResolutionReader,
        snapshots: SqlAlchemyRuntimeExecutionSnapshotRepository,
    ) -> None:
        self._sessions = sessions
        self._resolver = resolver
        self._reader = reader
        self._snapshots = snapshots

    async def materialize_runtime(self, tenant_id: str) -> RuntimeExecutionSnapshot:
        async with self._sessions.begin() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            resolution = self._resolver.resolve_state(
                tenant_id, await self._reader.load_in_session(session, tenant_id)
            )
            payload = snapshot_payload(tenant_id, resolution)
            snapshot = RuntimeExecutionSnapshot(
                uuid4(),
                SNAPSHOT_SCHEMA_VERSION,
                tenant_id,
                resolution.selected.architecture,
                datetime.now(UTC),
                resolution.selected,
                resolution,
                content_hash(payload),
            )
            return await self._snapshots.create(session, snapshot, payload)

    async def get_snapshot(self, snapshot_id: UUID) -> RuntimeExecutionSnapshot | None:
        return await self._snapshots.get(snapshot_id)
