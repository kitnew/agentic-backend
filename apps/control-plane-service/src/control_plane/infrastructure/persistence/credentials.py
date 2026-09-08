from collections.abc import Sequence

from sqlalchemy import func, select
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
    PlatformCredentialScope,
    TenantCredentialScope,
)
from control_plane.infrastructure.encryption import CredentialCipher

from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import IntegrationConnection as IntegrationConnectionRow
from .models import ProviderConnection as ProviderConnectionRow


class SqlAlchemyCredentialRepository:
    def __init__(self, session: AsyncSession, cipher: CredentialCipher) -> None:
        self._session = session
        self._cipher = cipher

    async def create(
        self, scope: CredentialScope, name: str, secret: str, actor: str
    ) -> Credential:
        row = CredentialRow(
            scope_type=scope.type,
            tenant_id=(
                scope.tenant_id if isinstance(scope, TenantCredentialScope) else None
            ),
            name=name,
            status=CredentialStatus.ACTIVE,
            created_by=actor,
        )
        self._session.add(row)
        await self._session.flush()
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
        self._session.add(version)
        await self._session.flush()
        row.active_version_id = version.id
        await self._session.flush()
        await self._session.refresh(row)
        return self._credential(row, 1)

    async def get(self, ref: CredentialRef, *, lock: bool = False) -> Credential:
        row = await self._session.get(CredentialRow, ref.value, with_for_update=lock)
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
        number = await self._active_version_number(row)
        if row.active_version_id is None or number is None:
            raise ManagedResourceConflict("credential has no active secret version")
        return self._credential(row, number)

    async def list(self, scope: CredentialScope | None = None) -> Sequence[Credential]:
        statement = select(CredentialRow).order_by(
            CredentialRow.scope_type, CredentialRow.tenant_id, CredentialRow.name
        )
        if isinstance(scope, PlatformCredentialScope):
            statement = statement.where(CredentialRow.scope_type == "platform")
        elif isinstance(scope, TenantCredentialScope):
            statement = statement.where(
                CredentialRow.scope_type == "tenant",
                CredentialRow.tenant_id == scope.tenant_id,
            )
        rows = (await self._session.scalars(statement)).all()
        credentials: list[Credential] = []
        for row in rows:
            number = await self._active_version_number(row)
            if row.active_version_id is None or number is None:
                raise ManagedResourceConflict("credential has no active secret version")
            credentials.append(self._credential(row, number))
        return credentials

    async def rotate(
        self, credential: Credential, secret: str, actor: str
    ) -> Credential:
        row = await self._row(credential.ref)
        active = await self._session.get(
            CredentialVersionRow, row.active_version_id, with_for_update=True
        )
        if active is None or active.retired_at is not None:
            raise ManagedResourceConflict("credential has no active secret version")
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
        self._session.add(version)
        await self._session.flush()
        row.active_version_id = version.id
        row.generation += 1
        await self._session.flush()
        await self._session.refresh(row)
        return self._credential(row, number)

    async def revoke(self, credential: Credential, actor: str) -> Credential:
        row = await self._row(credential.ref)
        row.status = CredentialStatus.REVOKED
        row.revoked_at = func.now()
        row.revoked_by = actor
        row.generation += 1
        await self._session.flush()
        await self._session.refresh(row)
        number = credential.active_secret_version_number
        if number is None:
            raise ManagedResourceConflict("credential has no active secret version")
        return self._credential(row, number)

    async def has_enabled_provider_connections(self, ref: CredentialRef) -> bool:
        return (
            await self._session.scalar(
                select(ProviderConnectionRow.id)
                .where(
                    ProviderConnectionRow.credential_id == ref.value,
                    ProviderConnectionRow.enabled.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    async def has_enabled_integration_connections(self, ref: CredentialRef) -> bool:
        return (
            await self._session.scalar(
                select(IntegrationConnectionRow.id)
                .where(
                    IntegrationConnectionRow.credential_id == ref.value,
                    IntegrationConnectionRow.enabled.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    async def _row(self, ref: CredentialRef) -> CredentialRow:
        row = await self._session.get(CredentialRow, ref.value)
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
        return row

    async def _active_version_number(self, row: CredentialRow) -> int | None:
        if row.active_version_id is None:
            return None
        return await self._session.scalar(
            select(CredentialVersionRow.version_number).where(
                CredentialVersionRow.id == row.active_version_id
            )
        )

    @staticmethod
    def _credential(row: CredentialRow, number: int) -> Credential:
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
