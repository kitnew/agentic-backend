from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.release_models import (
    ActivePhoneClaim,
    RuntimeBundleRecord,
    TenantAgentDraft,
    TenantAgentRevision,
    TenantCapabilitiesDraft,
    TenantCapabilitiesRevision,
    TenantKnowledgeComponentRevision,
    TenantKnowledgeDraft,
    TenantPromptComponentRevision,
    TenantPromptDraft,
    TenantRelease,
    TenantRuntimeComponentRevision,
    TenantRuntimeDraft,
    TenantTelephonyDraft,
    TenantTelephonyProvisioning,
    TenantTelephonyRevision,
)


class TenantComponent(StrEnum):
    RUNTIME = "runtime"
    AGENT = "agent"
    PROMPT = "prompt"
    KNOWLEDGE = "knowledge"
    CAPABILITIES = "capabilities"
    TELEPHONY = "telephony"


class DraftConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DraftExpectation:
    component: TenantComponent
    draft_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class ActiveReleaseRuntime:
    tenant: Tenant
    release: TenantRelease
    bundle: RuntimeBundleRecord


@dataclass(frozen=True, slots=True)
class InboundReleaseRuntime(ActiveReleaseRuntime):
    provisioning: TenantTelephonyProvisioning | None


_DRAFT_MODELS = {
    TenantComponent.RUNTIME: TenantRuntimeDraft,
    TenantComponent.AGENT: TenantAgentDraft,
    TenantComponent.PROMPT: TenantPromptDraft,
    TenantComponent.KNOWLEDGE: TenantKnowledgeDraft,
    TenantComponent.CAPABILITIES: TenantCapabilitiesDraft,
    TenantComponent.TELEPHONY: TenantTelephonyDraft,
}
_REVISION_MODELS = {
    TenantComponent.RUNTIME: TenantRuntimeComponentRevision,
    TenantComponent.AGENT: TenantAgentRevision,
    TenantComponent.PROMPT: TenantPromptComponentRevision,
    TenantComponent.KNOWLEDGE: TenantKnowledgeComponentRevision,
    TenantComponent.CAPABILITIES: TenantCapabilitiesRevision,
    TenantComponent.TELEPHONY: TenantTelephonyRevision,
}


class TenantReleaseRepository:
    """Private persistence helper; public APIs remain component-specific."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tenant_for_update(self, tenant_id: UUID) -> Tenant | None:
        return await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )

    async def active_release(self, tenant_id: UUID) -> TenantRelease | None:
        return await self._session.scalar(
            select(TenantRelease)
            .join(Tenant, Tenant.active_release_id == TenantRelease.id)
            .where(TenantRelease.tenant_id == tenant_id)
        )

    async def active_runtime(self, tenant_id: UUID) -> ActiveReleaseRuntime | None:
        row = (
            await self._session.execute(
                select(Tenant, TenantRelease, RuntimeBundleRecord)
                .join(TenantRelease, Tenant.active_release_id == TenantRelease.id)
                .join(
                    RuntimeBundleRecord,
                    and_(
                        RuntimeBundleRecord.id == TenantRelease.runtime_bundle_id,
                        RuntimeBundleRecord.tenant_id == Tenant.id,
                    ),
                )
                .where(Tenant.id == tenant_id)
            )
        ).one_or_none()
        return None if row is None else ActiveReleaseRuntime(*row)

    async def inbound_runtime(
        self, phone_number: str
    ) -> InboundReleaseRuntime | None:
        row = (
            await self._session.execute(
                select(
                    Tenant,
                    TenantRelease,
                    RuntimeBundleRecord,
                    TenantTelephonyProvisioning,
                )
                .join(ActivePhoneClaim, ActivePhoneClaim.tenant_id == Tenant.id)
                .join(TenantRelease, Tenant.active_release_id == TenantRelease.id)
                .join(
                    RuntimeBundleRecord,
                    and_(
                        RuntimeBundleRecord.id == TenantRelease.runtime_bundle_id,
                        RuntimeBundleRecord.tenant_id == Tenant.id,
                    ),
                )
                .outerjoin(
                    TenantTelephonyProvisioning,
                    TenantTelephonyProvisioning.tenant_id == Tenant.id,
                )
                .where(
                    ActivePhoneClaim.normalized_phone_number == phone_number,
                    ActivePhoneClaim.active_telephony_revision_id
                    == TenantRelease.telephony_revision_id,
                )
                .with_for_update(of=Tenant)
            )
        ).one_or_none()
        return None if row is None else InboundReleaseRuntime(*row)

    async def bundle_for_release(
        self,
        tenant_id: UUID,
        release_id: UUID,
        bundle_id: UUID,
    ) -> RuntimeBundleRecord | None:
        return await self._session.scalar(
            select(RuntimeBundleRecord)
            .join(
                TenantRelease,
                TenantRelease.runtime_bundle_id == RuntimeBundleRecord.id,
            )
            .where(
                TenantRelease.tenant_id == tenant_id,
                TenantRelease.id == release_id,
                TenantRelease.runtime_bundle_id == bundle_id,
                RuntimeBundleRecord.tenant_id == tenant_id,
            )
        )

    async def draft(self, component: TenantComponent, tenant_id: UUID) -> Any | None:
        model = _DRAFT_MODELS[component]
        return await self._session.scalar(
            select(model).where(model.tenant_id == tenant_id)
        )

    async def save_draft(
        self,
        *,
        component: TenantComponent,
        tenant_id: UUID,
        payload: dict[str, Any],
        expected_version: int | None,
        comment: str | None = None,
    ) -> Any:
        await self.tenant_for_update(tenant_id)
        model = _DRAFT_MODELS[component]
        draft = await self._session.scalar(
            select(model).where(model.tenant_id == tenant_id).with_for_update()
        )
        if draft is None:
            if expected_version is not None:
                raise DraftConflictError("draft does not exist")
            draft = model(tenant_id=tenant_id, payload=payload, comment=comment)
            self._session.add(draft)
        else:
            if expected_version != draft.version:
                raise DraftConflictError("draft version does not match")
            draft.payload = payload
            draft.comment = comment
            draft.version += 1
        await self._session.flush()
        return draft

    async def drafts_for_update(
        self,
        tenant_id: UUID,
        expectations: Sequence[DraftExpectation],
        *,
        require_complete_snapshot: bool = False,
    ) -> Mapping[TenantComponent, Any]:
        if len({item.component for item in expectations}) != len(expectations):
            raise DraftConflictError("component draft appears more than once")
        expected_by_component = {item.component: item for item in expectations}
        locked: dict[TenantComponent, Any] = {}
        for component, model in _DRAFT_MODELS.items():
            draft = await self._session.scalar(
                select(model)
                .where(model.tenant_id == tenant_id)
                .with_for_update()
            )
            expected = expected_by_component.get(component)
            if expected is None:
                if require_complete_snapshot and draft is not None:
                    raise DraftConflictError("publish-all snapshot has an extra draft")
                continue
            if (
                draft is None
                or draft.id != expected.draft_id
                or draft.version != expected.version
            ):
                raise DraftConflictError("draft no longer matches publish snapshot")
            locked[component] = draft
        return locked

    async def seal(
        self,
        tenant_id: UUID,
        drafts: Mapping[TenantComponent, Any],
    ) -> Mapping[TenantComponent, Any]:
        revisions: dict[TenantComponent, Any] = {}
        for component, draft in drafts.items():
            revision_model = _REVISION_MODELS[component]
            latest = await self._session.scalar(
                select(func.max(revision_model.revision_number)).where(
                    revision_model.tenant_id == tenant_id
                )
            )
            revision = revision_model(
                tenant_id=tenant_id,
                revision_number=(latest or 0) + 1,
                payload=draft.payload,
                created_by=draft.created_by,
                comment=draft.comment,
            )
            self._session.add(revision)
            revisions[component] = revision
        await self._session.flush()
        return revisions

    async def delete_drafts(self, drafts: Mapping[TenantComponent, Any]) -> None:
        for draft in drafts.values():
            await self._session.delete(draft)

    async def add_bundle(self, bundle: RuntimeBundleRecord) -> RuntimeBundleRecord:
        self._session.add(bundle)
        await self._session.flush()
        return bundle

    async def bundle_for_hash(
        self, tenant_id: UUID, content_hash: str
    ) -> RuntimeBundleRecord | None:
        return await self._session.scalar(
            select(RuntimeBundleRecord).where(
                RuntimeBundleRecord.tenant_id == tenant_id,
                RuntimeBundleRecord.content_hash == content_hash,
            )
        )

    async def next_release_number(self, tenant_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(TenantRelease.release_number)).where(
                TenantRelease.tenant_id == tenant_id
            )
        )
        return (latest or 0) + 1

    async def add_release(self, release: TenantRelease) -> TenantRelease:
        self._session.add(release)
        await self._session.flush()
        return release

    async def release_for_update(
        self, tenant_id: UUID, release_id: UUID
    ) -> TenantRelease | None:
        return await self._session.scalar(
            select(TenantRelease)
            .where(TenantRelease.tenant_id == tenant_id, TenantRelease.id == release_id)
            .with_for_update()
        )

    async def revision(
        self,
        component: TenantComponent,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> Any | None:
        model = _REVISION_MODELS[component]
        return await self._session.scalar(
            select(model).where(model.tenant_id == tenant_id, model.id == revision_id)
        )

    async def phone_claim_for_tenant(self, tenant_id: UUID) -> ActivePhoneClaim | None:
        return await self._session.scalar(
            select(ActivePhoneClaim)
            .where(ActivePhoneClaim.tenant_id == tenant_id)
            .with_for_update()
        )

    async def phone_claim(self, phone_number: str) -> ActivePhoneClaim | None:
        return await self._session.get(ActivePhoneClaim, phone_number)

    async def provisioning_for_update(
        self, tenant_id: UUID
    ) -> TenantTelephonyProvisioning | None:
        return await self._session.scalar(
            select(TenantTelephonyProvisioning)
            .where(TenantTelephonyProvisioning.tenant_id == tenant_id)
            .with_for_update()
        )

    async def add(self, value: object) -> None:
        self._session.add(value)
        await self._session.flush()

    async def delete(self, value: object) -> None:
        await self._session.delete(value)
        await self._session.flush()
