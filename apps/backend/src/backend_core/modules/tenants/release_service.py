from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from contracts.runtime_bundle import RuntimeBundleProvenance
from contracts.tenant_components import (
    TenantAgentConfig,
    TenantCapabilitiesConfig,
    TenantKnowledgeConfig,
    TenantPostCallConfig,
    TenantPromptConfig,
    TenantTelephonyConfig,
)
from contracts.voice_runtime import TenantRuntimeOverride
from pydantic import BaseModel, ValidationError

from backend_core.modules.tenants.release_compiler import CompiledRuntimeBundle
from backend_core.modules.tenants.release_models import (
    ActivePhoneClaim,
    RuntimeBundleRecord,
    TenantRelease,
    TenantTelephonyProvisioning,
)
from backend_core.modules.tenants.release_repository import (
    DraftExpectation,
    TenantComponent,
    TenantReleaseRepository,
)


class TenantReleaseError(Exception):
    pass


class TenantNotInitializedError(TenantReleaseError):
    pass


class InitialConfigurationIncompleteError(TenantReleaseError):
    def __init__(self, missing: set[TenantComponent]) -> None:
        super().__init__("initial tenant configuration is incomplete")
        self.missing = missing


class PhoneClaimConflictError(TenantReleaseError):
    pass


class ComponentDraftValidationError(TenantReleaseError):
    def __init__(self, component: TenantComponent, error: ValidationError) -> None:
        super().__init__(f"invalid {component} draft")
        self.component = component
        self.error = error


class _RevisionReference(Protocol):
    @property
    def id(self) -> UUID: ...

    payload: dict[str, object]


class _SealedRevision(_RevisionReference, Protocol):
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _InheritedRevision:
    id: UUID
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReleaseComponents:
    runtime: _RevisionReference
    agent: _RevisionReference
    prompt: _RevisionReference
    knowledge: _RevisionReference
    capabilities: _RevisionReference
    post_call: _RevisionReference
    telephony: _RevisionReference

    def id_for(self, component: TenantComponent) -> UUID:
        return getattr(self, component).id


BundleFactory = Callable[[ReleaseComponents], CompiledRuntimeBundle]


class TenantReleaseUseCases:
    """Coordinates drafts and releases; the supplied bundle factory must be pure."""

    def __init__(self, repository: TenantReleaseRepository) -> None:
        self._repository = repository

    async def publish(
        self,
        tenant_id: UUID,
        expectations: Sequence[DraftExpectation],
        bundle_factory: BundleFactory,
        *,
        comment: str | None = None,
        publish_all: bool = False,
    ) -> TenantRelease:
        tenant = await self._repository.tenant_for_update(tenant_id)
        if tenant is None:
            raise TenantReleaseError("tenant not found")

        expected_by_component = {item.component: item for item in expectations}
        drafts = await self._repository.drafts_for_update(
            tenant_id,
            expectations,
            require_complete_snapshot=publish_all,
        )
        active = await self._repository.active_release(tenant_id)
        if active is None:
            if not publish_all:
                raise TenantNotInitializedError
            missing = set(TenantComponent) - set(expected_by_component)
            if missing:
                raise InitialConfigurationIncompleteError(missing)
        elif not drafts:
            raise TenantReleaseError("at least one component draft is required")

        self._validate_drafts(drafts)
        sealed = await self._repository.seal(tenant_id, drafts)
        components = await self._components(tenant_id, active, sealed)
        compiled = bundle_factory(components)
        self._validate_provenance(compiled.bundle.provenance, components)

        bundle = await self._repository.bundle_for_hash(
            tenant_id, compiled.bundle.content_hash
        )
        if bundle is None:
            bundle = RuntimeBundleRecord(
                id=compiled.bundle.id,
                tenant_id=tenant_id,
                payload=compiled.bundle.payload.model_dump(mode="json"),
                provenance=compiled.bundle.provenance.model_dump(mode="json"),
                content_hash=compiled.bundle.content_hash,
                compiler_build_id=compiled.bundle.compiler_build_id,
            )
            await self._repository.add_bundle(bundle)
        release = TenantRelease(
            tenant_id=tenant_id,
            release_number=await self._repository.next_release_number(tenant_id),
            runtime_revision_id=components.runtime.id,
            agent_revision_id=components.agent.id,
            prompt_revision_id=components.prompt.id,
            knowledge_revision_id=components.knowledge.id,
            capabilities_revision_id=components.capabilities.id,
            post_call_revision_id=components.post_call.id,
            telephony_revision_id=components.telephony.id,
            runtime_bundle_id=bundle.id,
            comment=comment,
        )
        await self._repository.add_release(release)
        if active is None or TenantComponent.TELEPHONY in sealed:
            await self._update_telephony(tenant_id, sealed[TenantComponent.TELEPHONY])
        tenant.active_release_id = release.id
        await self._repository.delete_drafts(drafts)
        return release

    @staticmethod
    def _validate_drafts(
        drafts: Mapping[TenantComponent, _SealedRevision]
    ) -> None:
        models: dict[TenantComponent, type[BaseModel]] = {
            TenantComponent.RUNTIME: TenantRuntimeOverride,
            TenantComponent.AGENT: TenantAgentConfig,
            TenantComponent.PROMPT: TenantPromptConfig,
            TenantComponent.KNOWLEDGE: TenantKnowledgeConfig,
            TenantComponent.CAPABILITIES: TenantCapabilitiesConfig,
            TenantComponent.POST_CALL: TenantPostCallConfig,
            TenantComponent.TELEPHONY: TenantTelephonyConfig,
        }
        for component, draft in drafts.items():
            try:
                models[component].model_validate(draft.payload)
            except ValidationError as error:
                raise ComponentDraftValidationError(component, error) from error

    async def rollback(self, tenant_id: UUID, target_release_id: UUID) -> TenantRelease:
        tenant = await self._repository.tenant_for_update(tenant_id)
        if tenant is None:
            raise TenantReleaseError("tenant not found")
        target = await self._repository.release_for_update(tenant_id, target_release_id)
        if target is None:
            raise TenantReleaseError("release not found")
        if tenant.active_release_id == target.id:
            raise TenantReleaseError("target release is already active")
        telephony = await self._repository.revision(
            TenantComponent.TELEPHONY,
            tenant_id,
            target.telephony_revision_id,
        )
        if telephony is None:
            raise TenantReleaseError("release telephony revision not found")
        release = TenantRelease(
            tenant_id=tenant_id,
            release_number=await self._repository.next_release_number(tenant_id),
            runtime_revision_id=target.runtime_revision_id,
            agent_revision_id=target.agent_revision_id,
            prompt_revision_id=target.prompt_revision_id,
            knowledge_revision_id=target.knowledge_revision_id,
            capabilities_revision_id=target.capabilities_revision_id,
            post_call_revision_id=target.post_call_revision_id,
            telephony_revision_id=target.telephony_revision_id,
            runtime_bundle_id=target.runtime_bundle_id,
            source_release_id=target.id,
        )
        await self._repository.add_release(release)
        await self._update_telephony(tenant_id, telephony)
        tenant.active_release_id = release.id
        return release

    async def _components(
        self,
        tenant_id: UUID,
        active: TenantRelease | None,
        sealed: Mapping[TenantComponent, _RevisionReference],
    ) -> ReleaseComponents:
        async def revision(
            component: TenantComponent, attribute: str
        ) -> _RevisionReference:
            if component in sealed:
                return sealed[component]
            if active is None:
                raise TenantNotInitializedError
            inherited = await self._repository.revision(
                component, tenant_id, getattr(active, attribute)
            )
            if inherited is None:
                raise TenantReleaseError("active release component revision not found")
            return _InheritedRevision(id=inherited.id, payload=inherited.payload)

        return ReleaseComponents(
            runtime=await revision(TenantComponent.RUNTIME, "runtime_revision_id"),
            agent=await revision(TenantComponent.AGENT, "agent_revision_id"),
            prompt=await revision(TenantComponent.PROMPT, "prompt_revision_id"),
            knowledge=await revision(
                TenantComponent.KNOWLEDGE, "knowledge_revision_id"
            ),
            capabilities=await revision(
                TenantComponent.CAPABILITIES, "capabilities_revision_id"
            ),
            post_call=await revision(
                TenantComponent.POST_CALL, "post_call_revision_id"
            ),
            telephony=await revision(
                TenantComponent.TELEPHONY, "telephony_revision_id"
            ),
        )

    @staticmethod
    def _validate_provenance(
        provenance: RuntimeBundleProvenance, components: ReleaseComponents
    ) -> None:
        for component, provenance_id in (
            (TenantComponent.RUNTIME, provenance.runtime_revision_id),
            (TenantComponent.AGENT, provenance.agent_revision_id),
            (TenantComponent.PROMPT, provenance.prompt_revision_id),
            (TenantComponent.KNOWLEDGE, provenance.knowledge_revision_id),
            (TenantComponent.CAPABILITIES, provenance.capabilities_revision_id),
            (TenantComponent.POST_CALL, provenance.post_call_revision_id),
            (TenantComponent.TELEPHONY, provenance.telephony_revision_id),
        ):
            if components.id_for(component) != provenance_id:
                raise TenantReleaseError("bundle provenance does not match release")

    async def _update_telephony(
        self, tenant_id: UUID, revision: _SealedRevision
    ) -> None:
        telephony = TenantTelephonyConfig.model_validate(revision.payload)
        existing = await self._repository.phone_claim_for_tenant(tenant_id)
        if (
            existing is not None
            and existing.normalized_phone_number == telephony.phone_number
        ):
            existing.active_telephony_revision_id = revision.id
        else:
            if existing is not None:
                await self._repository.delete(existing)
            if telephony.phone_number is not None:
                owner = await self._repository.phone_claim(telephony.phone_number)
                if owner is not None and owner.tenant_id != tenant_id:
                    raise PhoneClaimConflictError
                await self._repository.add(
                    ActivePhoneClaim(
                        normalized_phone_number=telephony.phone_number,
                        tenant_id=tenant_id,
                        active_telephony_revision_id=revision.id,
                    )
                )
        state = await self._repository.provisioning_for_update(tenant_id)
        if state is None:
            await self._repository.add(
                TenantTelephonyProvisioning(
                    tenant_id=tenant_id,
                    desired_revision_id=revision.id,
                )
            )
        elif state.desired_revision_id != revision.id:
            state.desired_revision_id = revision.id
            state.status = "pending"
