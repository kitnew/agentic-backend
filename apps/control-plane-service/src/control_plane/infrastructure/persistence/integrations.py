from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.managed_resource_errors import (
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialScope,
    CredentialStatus,
    IntegrationConnection,
    IntegrationConnectionRef,
    PlatformCredentialScope,
    TenantCredentialScope,
)

from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import IntegrationConnection as IntegrationRow


class SqlAlchemyIntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        tenant_id: str,
        key: str,
        integration_kind: str,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        actor: str,
    ) -> IntegrationConnection:
        row = IntegrationRow(
            tenant_id=tenant_id,
            key=key,
            integration_kind=integration_kind,
            config=config,
            credential_id=credential_ref.value if credential_ref else None,
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
        connection: IntegrationConnection,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        actor: str,
    ) -> IntegrationConnection:
        row = await self._row(connection.ref)
        row.config = config
        row.credential_id = credential_ref.value if credential_ref else None
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def set_enabled(
        self, connection: IntegrationConnection, enabled: bool, actor: str
    ) -> IntegrationConnection:
        row = await self._row(connection.ref)
        row.enabled = enabled
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._value(row)

    async def get(
        self, ref: IntegrationConnectionRef, *, lock: bool = False
    ) -> IntegrationConnection:
        return self._value(await self._row(ref, lock=lock))

    async def get_by_key(
        self, tenant_id: str, key: str, *, lock: bool = False
    ) -> IntegrationConnection:
        statement = select(IntegrationRow).where(
            IntegrationRow.tenant_id == tenant_id, IntegrationRow.key == key
        )
        row = await self._session.scalar(
            statement.with_for_update() if lock else statement
        )
        if row is None:
            raise ManagedResourceNotFound(f"integration {key} not found for tenant")
        return self._value(row)

    async def list(self, tenant_id: str) -> Sequence[IntegrationConnection]:
        rows = (
            await self._session.scalars(
                select(IntegrationRow)
                .where(IntegrationRow.tenant_id == tenant_id)
                .order_by(IntegrationRow.key)
            )
        ).all()
        return [self._value(row) for row in rows]

    async def get_credential(
        self, ref: CredentialRef, *, lock: bool = False
    ) -> Credential:
        row = await self._session.get(CredentialRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
        if row.active_version_id is None:
            raise ManagedResourceConflict("credential has no active secret version")
        number = await self._session.scalar(
            select(CredentialVersionRow.version_number).where(
                CredentialVersionRow.id == row.active_version_id
            )
        )
        if number is None:
            raise ManagedResourceConflict("credential has no active secret version")
        scope: CredentialScope = (
            TenantCredentialScope(row.tenant_id)
            if row.scope_type == "tenant" and row.tenant_id is not None
            else PlatformCredentialScope()
        )
        return Credential(
            CredentialRef(row.id),
            scope,
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

    async def _row(
        self, ref: IntegrationConnectionRef, *, lock: bool = False
    ) -> IntegrationRow:
        row = await self._session.get(IntegrationRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(
                f"integration connection {ref.value} not found"
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
    def _value(row: IntegrationRow) -> IntegrationConnection:
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
