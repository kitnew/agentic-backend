from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts import (
    TENANT_CONFIG_SCHEMAS,
    EffectiveVoiceRuntime,
    PlatformRuntimePolicy,
    TenantConfigV2,
    TenantConfigV3,
    TenantRuntimeOverride,
)
from pydantic import ValidationError

from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    Tenant,
    TenantStatus,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.runtime.voice.errors import (
    RuntimeDraftExistsError,
    RuntimeNotFoundError,
    RuntimeRevisionImmutableError,
    RuntimeRevisionVersionConflictError,
    VoiceRuntimeResolutionError,
)
from backend_core.runtime.voice.models import (
    PlatformRuntime,
    PlatformRuntimeRevision,
    RuntimeRevisionStatus,
    TenantRuntime,
    TenantRuntimeRevision,
    VoiceRuntime,
    VoiceRuntimeRevision,
)
from backend_core.runtime.voice.repository import VoiceRuntimeRepository
from backend_core.runtime.voice.schemas import (
    PlatformRuntimeRevisionResponse,
    PlatformRuntimeStateResponse,
    TenantRuntimeRevisionResponse,
    TenantRuntimeStateResponse,
    VoiceRuntimeApplyResponse,
    VoiceRuntimeChange,
    VoiceRuntimePlanResponse,
    VoiceRuntimePlanStatus,
    VoiceRuntimeRevisionResponse,
)


class VoiceRuntimeUseCases:
    def __init__(
        self,
        tenants: TenantRepository,
        configs: ConfigRevisionRepository,
        runtimes: VoiceRuntimeRepository,
    ) -> None:
        self._tenants = tenants
        self._configs = configs
        self._runtimes = runtimes

    async def platform_state(self) -> PlatformRuntimeStateResponse:
        platform = await self._runtimes.platform()
        if platform is None:
            return PlatformRuntimeStateResponse(
                latest_published_revision=None, draft_revision=None
            )
        published = await self._runtimes.published_platform_revision(platform.id)
        draft = await self._runtimes.platform_draft(platform.id)
        return PlatformRuntimeStateResponse(
            latest_published_revision=(
                None
                if published is None
                else PlatformRuntimeRevisionResponse.model_validate(published)
            ),
            draft_revision=(
                None
                if draft is None
                else PlatformRuntimeRevisionResponse.model_validate(draft)
            ),
        )

    async def platform_revisions(self) -> list[PlatformRuntimeRevision]:
        return await self._runtimes.platform_revisions()

    async def create_platform_draft(
        self, policy: PlatformRuntimePolicy
    ) -> PlatformRuntimeRevision:
        platform = await self._runtimes.platform(lock=True)
        if platform is None:
            platform = PlatformRuntime(key="default")
            await self._runtimes.add(platform)
        if await self._runtimes.platform_draft(platform.id) is not None:
            raise RuntimeDraftExistsError
        revision = PlatformRuntimeRevision(
            platform_runtime_id=platform.id,
            revision_number=await self._runtimes.next_platform_revision_number(
                platform.id
            ),
            policy=policy.model_dump(mode="json"),
        )
        await self._runtimes.add(revision)
        return revision

    async def update_platform_draft(
        self,
        revision_id: UUID,
        policy: PlatformRuntimePolicy,
        expected_version: int,
    ) -> PlatformRuntimeRevision:
        revision = await self._runtimes.platform_revision(revision_id, lock=True)
        if revision is None:
            raise RuntimeNotFoundError
        self._check_mutable(revision.status, revision.version, expected_version)
        normalized = policy.model_dump(mode="json")
        if revision.policy != normalized:
            revision.policy = normalized
            revision.version += 1
            await self._runtimes.flush()
        return revision

    async def publish_platform(self, revision_id: UUID) -> PlatformRuntimeRevision:
        platform = await self._runtimes.platform(lock=True)
        if platform is None:
            raise RuntimeNotFoundError
        revision = await self._runtimes.platform_revision(revision_id, lock=True)
        if revision is None or revision.platform_runtime_id != platform.id:
            raise RuntimeNotFoundError
        if revision.status is not RuntimeRevisionStatus.DRAFT:
            raise RuntimeRevisionImmutableError
        PlatformRuntimePolicy.model_validate(revision.policy)
        revision.status = RuntimeRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        await self._runtimes.flush()
        return revision

    async def tenant_state(self, tenant_id: UUID) -> TenantRuntimeStateResponse:
        await self._tenant(tenant_id)
        runtime = await self._runtimes.tenant_runtime(tenant_id)
        if runtime is None:
            return TenantRuntimeStateResponse(
                latest_published_revision=None, draft_revision=None
            )
        published = await self._runtimes.published_tenant_revision(runtime.id)
        draft = await self._runtimes.tenant_draft(runtime.id)
        return TenantRuntimeStateResponse(
            latest_published_revision=(
                None
                if published is None
                else TenantRuntimeRevisionResponse.model_validate(published)
            ),
            draft_revision=(
                None
                if draft is None
                else TenantRuntimeRevisionResponse.model_validate(draft)
            ),
        )

    async def tenant_revisions(self, tenant_id: UUID) -> list[TenantRuntimeRevision]:
        await self._tenant(tenant_id)
        return await self._runtimes.tenant_revisions(tenant_id)

    async def create_tenant_draft(
        self, tenant_id: UUID, settings: TenantRuntimeOverride
    ) -> TenantRuntimeRevision:
        await self._tenant(tenant_id, lock=True)
        runtime = await self._runtimes.tenant_runtime(tenant_id, lock=True)
        if runtime is None:
            runtime = TenantRuntime(tenant_id=tenant_id)
            await self._runtimes.add(runtime)
        if await self._runtimes.tenant_draft(runtime.id) is not None:
            raise RuntimeDraftExistsError
        revision = TenantRuntimeRevision(
            tenant_runtime_id=runtime.id,
            tenant_id=tenant_id,
            revision_number=await self._runtimes.next_tenant_revision_number(
                runtime.id
            ),
            settings=settings.model_dump(mode="json", exclude_none=True),
        )
        await self._runtimes.add(revision)
        return revision

    async def update_tenant_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        settings: TenantRuntimeOverride,
        expected_version: int,
    ) -> TenantRuntimeRevision:
        await self._tenant(tenant_id, lock=True)
        revision = await self._runtimes.tenant_revision(
            tenant_id, revision_id, lock=True
        )
        if revision is None:
            raise RuntimeNotFoundError
        self._check_mutable(revision.status, revision.version, expected_version)
        normalized = settings.model_dump(mode="json", exclude_none=True)
        if revision.settings != normalized:
            revision.settings = normalized
            revision.version += 1
            await self._runtimes.flush()
        return revision

    async def publish_tenant(
        self, tenant_id: UUID, revision_id: UUID
    ) -> TenantRuntimeRevision:
        await self._tenant(tenant_id, lock=True)
        revision = await self._runtimes.tenant_revision(
            tenant_id, revision_id, lock=True
        )
        if revision is None:
            raise RuntimeNotFoundError
        if revision.status is not RuntimeRevisionStatus.DRAFT:
            raise RuntimeRevisionImmutableError
        TenantRuntimeOverride.model_validate(revision.settings)
        revision.status = RuntimeRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        await self._runtimes.flush()
        return revision

    async def active_voice_runtime(
        self, tenant_id: UUID
    ) -> VoiceRuntimeRevision | None:
        tenant = await self._tenant(tenant_id)
        if tenant.active_voice_runtime_revision_id is None:
            return None
        return await self._runtimes.voice_revision(
            tenant_id, tenant.active_voice_runtime_revision_id
        )

    async def voice_revisions(self, tenant_id: UUID) -> list[VoiceRuntimeRevision]:
        await self._tenant(tenant_id)
        return await self._runtimes.voice_revisions(tenant_id)

    async def plan_voice_runtime(self, tenant_id: UUID) -> VoiceRuntimePlanResponse:
        tenant = await self._tenant(tenant_id)
        desired, platform_revision, tenant_revision = await self._resolve(tenant)
        active = await self.active_voice_runtime(tenant_id)
        return self._plan(active, desired, platform_revision, tenant_revision)

    async def apply_voice_runtime(self, tenant_id: UUID) -> VoiceRuntimeApplyResponse:
        tenant = await self._tenant(tenant_id, lock=True)
        platform = await self._runtimes.platform(lock=True)
        if platform is None:
            raise self._resolution_error(
                "platform_runtime", "published_platform_runtime_not_found"
            )
        desired, platform_revision, tenant_revision = await self._resolve(
            tenant, platform
        )
        active = (
            None
            if tenant.active_voice_runtime_revision_id is None
            else await self._runtimes.voice_revision(
                tenant_id, tenant.active_voice_runtime_revision_id, lock=True
            )
        )
        if tenant.active_voice_runtime_revision_id is not None and active is None:
            raise self._resolution_error(
                "tenant.active_voice_runtime_revision_id",
                "active_voice_runtime_not_found",
            )
        desired_payload = desired.model_dump(mode="json")
        if active is not None and active.effective_settings == desired_payload:
            return VoiceRuntimeApplyResponse(
                changed=False,
                voice_runtime=VoiceRuntimeRevisionResponse.model_validate(active),
            )
        runtime = await self._runtimes.voice_runtime(tenant_id, lock=True)
        if runtime is None:
            runtime = VoiceRuntime(tenant_id=tenant_id)
            await self._runtimes.add(runtime)
        if active is not None:
            active.status = RuntimeRevisionStatus.ARCHIVED
        revision = VoiceRuntimeRevision(
            voice_runtime_id=runtime.id,
            tenant_id=tenant_id,
            revision_number=await self._runtimes.next_voice_revision_number(runtime.id),
            status=RuntimeRevisionStatus.PUBLISHED,
            platform_runtime_revision_id=platform_revision.id,
            tenant_runtime_revision_id=(
                None if tenant_revision is None else tenant_revision.id
            ),
            effective_settings=desired_payload,
            published_at=datetime.now(UTC),
        )
        await self._runtimes.add(revision)
        tenant.active_voice_runtime_revision_id = revision.id
        await self._runtimes.flush()
        return VoiceRuntimeApplyResponse(
            changed=True,
            voice_runtime=VoiceRuntimeRevisionResponse.model_validate(revision),
        )

    async def _resolve(
        self, tenant: Tenant, platform: PlatformRuntime | None = None
    ) -> tuple[
        EffectiveVoiceRuntime,
        PlatformRuntimeRevision,
        TenantRuntimeRevision | None,
    ]:
        if tenant.status is not TenantStatus.ACTIVE:
            raise self._resolution_error("tenant.status", "tenant_not_active")
        if tenant.active_config_revision_id is None:
            raise self._resolution_error(
                "tenant.active_config_revision_id", "active_config_not_found"
            )
        config_revision = await self._configs.get(
            tenant.id, tenant.active_config_revision_id
        )
        if (
            config_revision is None
            or config_revision.status is not ConfigRevisionStatus.PUBLISHED
            or config_revision.published_at is None
        ):
            raise self._resolution_error(
                "tenant.active_config_revision_id", "active_config_invalid"
            )
        schema = TENANT_CONFIG_SCHEMAS.get(config_revision.schema_version)
        try:
            config = (
                None
                if schema is None
                else schema.model_validate(config_revision.config)
            )
        except ValidationError as error:
            raise self._resolution_error(
                "tenant.active_config_revision_id", "active_config_invalid"
            ) from error
        if not isinstance(config, (TenantConfigV2, TenantConfigV3)):
            raise self._resolution_error(
                "tenant.active_config_revision_id", "active_config_invalid"
            )
        locale = config.localization.default_locale
        if locale.partition("-")[0].lower() != "sk":
            raise self._resolution_error(
                "localization.default_locale", "unsupported_locale"
            )
        platform = platform or await self._runtimes.platform()
        if platform is None:
            raise self._resolution_error(
                "platform_runtime", "published_platform_runtime_not_found"
            )
        platform_revision = await self._runtimes.published_platform_revision(
            platform.id
        )
        if platform_revision is None:
            raise self._resolution_error(
                "platform_runtime", "published_platform_runtime_not_found"
            )
        tenant_runtime = await self._runtimes.tenant_runtime(tenant.id)
        tenant_revision = (
            None
            if tenant_runtime is None
            else await self._runtimes.published_tenant_revision(tenant_runtime.id)
        )
        try:
            policy = PlatformRuntimePolicy.model_validate(platform_revision.policy)
            override = (
                TenantRuntimeOverride()
                if tenant_revision is None
                else TenantRuntimeOverride.model_validate(tenant_revision.settings)
            )
        except ValidationError as error:
            raise self._resolution_error(
                "runtime_revision", "invalid_published_runtime"
            ) from error
        payload = policy.model_dump(mode="json")
        if override.tts is not None:
            payload["tts"]["voice_id"] = override.tts.voice_id
        return (
            EffectiveVoiceRuntime.model_validate({"locale": locale, **payload}),
            platform_revision,
            tenant_revision,
        )

    def _plan(
        self,
        active: VoiceRuntimeRevision | None,
        desired: EffectiveVoiceRuntime,
        platform_revision: PlatformRuntimeRevision,
        tenant_revision: TenantRuntimeRevision | None,
    ) -> VoiceRuntimePlanResponse:
        desired_payload = desired.model_dump(mode="json")
        if active is None:
            status = VoiceRuntimePlanStatus.MISSING_ACTIVE
            changes: list[VoiceRuntimeChange] = []
        else:
            changes = self._changes(active.effective_settings, desired_payload)
            status = (
                VoiceRuntimePlanStatus.UNCHANGED
                if not changes
                else VoiceRuntimePlanStatus.MODIFIED
            )
        return VoiceRuntimePlanResponse(
            status=status,
            active_revision=(
                None
                if active is None
                else VoiceRuntimeRevisionResponse.model_validate(active)
            ),
            desired_settings=desired,
            platform_runtime_revision_id=platform_revision.id,
            tenant_runtime_revision_id=(
                None if tenant_revision is None else tenant_revision.id
            ),
            changes=changes,
        )

    def _changes(
        self, before: dict[str, Any], after: dict[str, Any], path: str = ""
    ) -> list[VoiceRuntimeChange]:
        changes: list[VoiceRuntimeChange] = []
        for key, new in after.items():
            child = f"{path}.{key}".strip(".")
            old = before.get(key)
            if isinstance(old, dict) and isinstance(new, dict):
                changes.extend(self._changes(old, new, child))
            elif old != new:
                changes.append(VoiceRuntimeChange(path=child, before=old, after=new))
        return changes

    async def _tenant(self, tenant_id: UUID, *, lock: bool = False) -> Tenant:
        tenant = (
            await self._tenants.get_for_update(tenant_id)
            if lock
            else await self._tenants.get(tenant_id)
        )
        if tenant is None:
            raise RuntimeNotFoundError
        return tenant

    @staticmethod
    def _check_mutable(
        status: RuntimeRevisionStatus, version: int, expected_version: int
    ) -> None:
        if status is not RuntimeRevisionStatus.DRAFT:
            raise RuntimeRevisionImmutableError
        if version != expected_version:
            raise RuntimeRevisionVersionConflictError

    @staticmethod
    def _resolution_error(path: str, code: str) -> VoiceRuntimeResolutionError:
        return VoiceRuntimeResolutionError(path, code, code.replace("_", " "))
