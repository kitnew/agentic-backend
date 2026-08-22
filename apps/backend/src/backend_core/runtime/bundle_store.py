from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PinnedRuntimeBundle:
    payload: dict[str, object]
    provenance: dict[str, object]


class RuntimeBundleStore:
    """Runtime-only read boundary for a call's immutable bundle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: UUID, release_id: UUID, bundle_id: UUID
    ) -> PinnedRuntimeBundle | None:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT b.payload, b.provenance
                    FROM runtime_bundles AS b
                    JOIN tenant_releases AS r ON r.runtime_bundle_id = b.id
                    WHERE r.tenant_id = :tenant_id AND r.id = :release_id
                      AND b.tenant_id = :tenant_id AND b.id = :bundle_id
                    """
                ),
                {"tenant_id": tenant_id, "release_id": release_id, "bundle_id": bundle_id},
            )
        ).one_or_none()
        return None if row is None else PinnedRuntimeBundle(row.payload, row.provenance)

    async def telephony_ready(self, tenant_id: UUID, revision_id: UUID) -> bool:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT status, desired_revision_id, applied_revision_id
                    FROM tenant_telephony_provisioning
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).one_or_none()
        return bool(
            row is not None
            and row.status == "ready"
            and row.desired_revision_id == revision_id
            and row.applied_revision_id == revision_id
        )

    async def tenant_active(self, tenant_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM tenants WHERE id = :tenant_id AND status = 'active')"
                ),
                {"tenant_id": tenant_id},
            )
        )
