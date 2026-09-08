from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
)
from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.runtime_resolver import (
    RuntimeResolutionReader,
    RuntimeResolver,
)
from control_plane.domain.runtime_execution_snapshot import ExecutionSnapshot
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)


class ExecutionSnapshotService:
    """Temporary Slice 12 adapter over the single target materialization path."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        _resolver: RuntimeResolver,
        reader: RuntimeResolutionReader,
        snapshots: SqlAlchemyExecutionSnapshotRepository,
        execution_resolver: ExecutionResolver | None = None,
        materialization: ExecutionMaterializationService | None = None,
    ) -> None:
        self._materialization = materialization or ExecutionMaterializationService(
            sessions, None, snapshots, execution_resolver, reader
        )

    async def materialize(self, tenant_id: str) -> ExecutionSnapshot:
        return await self._materialization.create_snapshot(tenant_id)

    async def get_snapshot(self, snapshot_id: UUID) -> ExecutionSnapshot | None:
        return await self._materialization.get_snapshot(snapshot_id)

    async def materialize_runtime(self, tenant_id: str) -> ExecutionSnapshot:
        return await self.materialize(tenant_id)
