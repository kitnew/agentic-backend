from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.runtime_resolver import (
    RuntimeResolutionReader,
    RuntimeResolver,
)
from control_plane.domain.runtime_execution_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ExecutionSnapshot,
    content_hash,
    snapshot_payload,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)


class ExecutionSnapshotService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        resolver: RuntimeResolver,
        reader: RuntimeResolutionReader,
        snapshots: SqlAlchemyExecutionSnapshotRepository,
        execution_resolver: ExecutionResolver | None = None,
    ) -> None:
        self._sessions = sessions
        self._resolver = resolver
        self._execution_resolver = execution_resolver
        self._reader = reader
        self._snapshots = snapshots

    async def materialize(self, tenant_id: str) -> ExecutionSnapshot:
        async with self._sessions.begin() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            if self._execution_resolver is None:
                resolution = self._resolver.resolve_state(
                    tenant_id, await self._reader.load_in_session(session, tenant_id)
                )
                payload = snapshot_payload(tenant_id, resolution)
                snapshot = ExecutionSnapshot(
                    uuid4(),
                    SNAPSHOT_SCHEMA_VERSION,
                    tenant_id,
                    resolution.selected.architecture,
                    datetime.now(UTC),
                    cast(dict[str, object], payload["execution"]),
                    None,
                    resolution.selected,
                    resolution,
                    content_hash(payload),
                )
                return await self._snapshots.create(session, snapshot, payload)
            execution = self._execution_resolver.resolve_state(
                tenant_id, await self._reader.load_in_session(session, tenant_id)
            )
            payload = snapshot_payload(
                tenant_id,
                execution.runtime,
                {
                    "runtime": execution.runtime.selected,
                    "agent": execution.agent,
                    "prompts": execution.prompts,
                    "knowledge": execution.knowledge,
                    "capabilities": execution.capabilities,
                    "post_call": execution.post_call,
                    "handoff": execution.handoff,
                    "phone_assignment": execution.phone_assignment,
                    "provenance": execution.provenance,
                },
            )
            snapshot = ExecutionSnapshot(
                uuid4(),
                SNAPSHOT_SCHEMA_VERSION,
                tenant_id,
                execution.architecture,
                datetime.now(UTC),
                cast(dict[str, object], payload["execution"]),
                execution.agent,
                execution.runtime.selected,
                execution.runtime,
                content_hash(payload),
            )
            return await self._snapshots.create(session, snapshot, payload)

    async def get_snapshot(self, snapshot_id: UUID) -> ExecutionSnapshot | None:
        return await self._snapshots.get(snapshot_id)

    async def materialize_runtime(self, tenant_id: str) -> ExecutionSnapshot:
        return await self.materialize(tenant_id)
