from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.runtime_resolver import (
    RuntimeResolutionReader,
    RuntimeResolutionState,
    StoredActiveRuntimeComponent,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)

from .models import ConfigurationComponent as ComponentRow
from .models import ConfigurationComponentRevision as RevisionRow
from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import ModelDeployment as DeploymentRow
from .models import ProviderConnection as ConnectionRow

_PLATFORM_KINDS = (
    "runtime.llm.defaults",
    "runtime.stt.defaults",
    "runtime.tts.defaults",
    "runtime.cascade.execution.defaults",
    "runtime.realtime.execution.defaults",
)
_TENANT_KINDS = (
    "runtime.architecture.policy",
    "runtime.speech.overrides",
)


class SqlAlchemyRuntimeResolutionReader(RuntimeResolutionReader):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, tenant_id: str) -> RuntimeResolutionState:
        async with self._sessions.begin() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            return await self.load_in_session(session, tenant_id)

    async def load_in_session(
        self, session: AsyncSession, tenant_id: str
    ) -> RuntimeResolutionState:
            components = await self._components(session, tenant_id)
            deployment_ids = self._deployment_ids(components.values())
            deployments = (
                {
                    row.id: self._deployment(row)
                    for row in (
                        await session.scalars(
                            select(DeploymentRow).where(
                                DeploymentRow.id.in_(deployment_ids)
                            )
                        )
                    ).all()
                }
                if deployment_ids
                else {}
            )
            connection_ids = {
                value.connection_ref.value for value in deployments.values()
            }
            connections = (
                {
                    row.id: self._connection(row)
                    for row in (
                        await session.scalars(
                            select(ConnectionRow).where(
                                ConnectionRow.id.in_(connection_ids)
                            )
                        )
                    ).all()
                }
                if connection_ids
                else {}
            )
            credential_ids = {
                value.credential_ref.value for value in connections.values()
            }
            credentials: dict[UUID, Credential] = {}
            if credential_ids:
                rows = (
                    await session.scalars(
                        select(CredentialRow).where(
                            CredentialRow.id.in_(credential_ids)
                        )
                    )
                ).all()
                for row in rows:
                    number = (
                        await session.scalar(
                            select(CredentialVersionRow.version_number).where(
                                CredentialVersionRow.id == row.active_version_id
                            )
                        )
                        if row.active_version_id
                        else None
                    )
                    credentials[row.id] = self._credential(row, number)
            return RuntimeResolutionState(
                components, deployments, connections, credentials
            )

    @staticmethod
    async def _components(
        session: AsyncSession, tenant_id: str
    ) -> dict[ComponentAddress, StoredActiveRuntimeComponent]:
        rows = (
            await session.execute(
                select(ComponentRow, RevisionRow)
                .join(RevisionRow, RevisionRow.id == ComponentRow.active_revision_id)
                .where(
                    or_(
                        (
                            (ComponentRow.scope_type == "platform")
                            & ComponentRow.kind.in_(_PLATFORM_KINDS)
                        ),
                        (
                            (ComponentRow.scope_type == "tenant")
                            & (ComponentRow.scope_key == tenant_id)
                            & ComponentRow.kind.in_(_TENANT_KINDS)
                        ),
                    )
                )
            )
        ).all()
        result: dict[ComponentAddress, StoredActiveRuntimeComponent] = {}
        for component, revision in rows:
            scope = (
                PlatformScope()
                if component.scope_type == "platform"
                else TenantScope(tenant_id)
            )
            address = ComponentAddress(ComponentKind(component.kind), scope)
            result[address] = StoredActiveRuntimeComponent(
                address,
                revision.id,
                revision.revision_number,
                revision.schema_version,
                dict(revision.value),
            )
        return result

    @staticmethod
    def _deployment_ids(
        components: Iterable[StoredActiveRuntimeComponent],
    ) -> set[UUID]:
        result: set[UUID] = set()
        for component in components:
            raw = component.value.get("deployment_ref")
            if raw:
                try:
                    result.add(UUID(str(raw)))
                except ValueError:
                    pass
            transcription = component.value.get("input_transcription")
            if isinstance(transcription, dict) and transcription.get("deployment_ref"):
                try:
                    result.add(UUID(str(transcription["deployment_ref"])))
                except ValueError:
                    pass
        return result

    @staticmethod
    def _deployment(row: DeploymentRow) -> ModelDeployment:
        return ModelDeployment(
            ModelDeploymentRef(row.id),
            row.key,
            ProviderConnectionRef(row.connection_id),
            DeploymentKind(row.deployment_kind),
            dict(row.deployment_config),
            LLMCapabilities(**row.llm_capabilities) if row.llm_capabilities else None,
            RealtimeCapabilities(**row.realtime_capabilities)
            if row.realtime_capabilities
            else None,
            STTCapabilities(**row.stt_capabilities) if row.stt_capabilities else None,
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _connection(row: ConnectionRow) -> ProviderConnection:
        return ProviderConnection(
            ProviderConnectionRef(row.id),
            row.key,
            row.provider_kind,
            CredentialRef(row.credential_id),
            dict(row.connection_config),
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _credential(row: CredentialRow, number: int | None) -> Credential:
        return Credential(
            CredentialRef(row.id),
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
