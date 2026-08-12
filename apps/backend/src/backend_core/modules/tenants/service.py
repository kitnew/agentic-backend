from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from contracts import (
    TENANT_CONFIG_SCHEMAS,
    TenantCapabilityProfile,
    TenantConfig,
    TenantConfigV2,
    TenantConfigV3,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.integrations.models import (
    IntegrationConnectionStatus,
    provider_for_plan_type,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotFoundError,
    ConfigRevisionVersionConflictError,
    InboundRouteDidConflictError,
    InboundRouteNotFoundError,
    InboundRouteUnavailableError,
    InvalidPromptSetError,
    InvalidTenantConfigError,
    PromptRevisionActiveDraftExistsError,
    PromptRevisionImmutableError,
    PromptRevisionNotFoundError,
    PromptRevisionVersionConflictError,
    PromptSetResolutionError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.knowledge import (
    knowledge_content_hash,
    knowledge_content_matches,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    KnowledgeBase,
    KnowledgeBaseRevision,
    KnowledgeBaseRevisionDocument,
    KnowledgeDocument,
    KnowledgeDocumentRevision,
    ProfilePrompt,
    ProfilePromptRevision,
    PromptRevisionStatus,
    PromptSet,
    PromptSetRevision,
    SystemPrompt,
    SystemPromptRevision,
    Tenant,
    TenantConfigRevision,
    TenantPrompt,
    TenantPromptRevision,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptCompositionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    CreateDraftRequest,
    CreateInboundRouteRequest,
    CreatePlatformPromptDraftRequest,
    CreatePromptSetDraftRequest,
    CreateTenantRequest,
    CreateTextDraftRequest,
    KnowledgeBasePlanResponse,
    KnowledgeBasePublishResponse,
    KnowledgeBasePushResponse,
    KnowledgeBaseRevisionResponse,
    KnowledgeBaseSnapshotResponse,
    KnowledgeBaseStateResponse,
    KnowledgeDocumentPlanResponse,
    KnowledgeDocumentRevisionResponse,
    KnowledgeDocumentsRequest,
    KnowledgeDocumentSummaryResponse,
    PromptSetApplyResponse,
    PromptSetComponentPlanResponse,
    PromptSetComponentResponse,
    PromptSetCompositionResponse,
    PromptSetDetailResponse,
    PromptSetPlanComponentsResponse,
    PromptSetPlanResponse,
    PromptSetRevisionResponse,
    UpdateDraftRequest,
    UpdateInboundRouteRequest,
    UpdatePromptSetDraftRequest,
    UpdateTextDraftRequest,
    ValidateConfigRequest,
    ValidationIssue,
)
from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    compile_plan,
    definition,
    normalize_input,
    validate_agent_input,
    validate_agent_schema,
    validate_business_input,
)

SYSTEM_PROMPT_KEY = "default"


class TenantService:
    def __init__(self, repository: TenantRepository) -> None:
        self._repository = repository

    async def create(self, data: CreateTenantRequest) -> Tenant:
        if await self._repository.get_by_slug(data.slug):
            raise TenantSlugConflictError

        tenant = Tenant(**data.model_dump())
        try:
            return await self._repository.add(tenant)
        except IntegrityError as error:
            raise TenantSlugConflictError from error

    async def get(self, tenant_id: UUID) -> Tenant:
        tenant = await self._repository.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        tenant = await self._repository.get_by_slug(slug)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def list(self, *, offset: int, limit: int) -> list[Tenant]:
        return await self._repository.list(offset=offset, limit=limit)


class InboundRouteService:
    def __init__(
        self,
        tenants: TenantRepository,
        routes: InboundRouteRepository,
    ) -> None:
        self._tenants = tenants
        self._routes = routes

    async def create(
        self,
        tenant_id: UUID,
        data: CreateInboundRouteRequest,
    ) -> InboundRoute:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        route = InboundRoute(tenant_id=tenant_id, **data.model_dump())
        try:
            return await self._routes.add(route)
        except IntegrityError as error:
            raise InboundRouteDidConflictError from error

    async def list(self, tenant_id: UUID) -> list[InboundRoute]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._routes.list(tenant_id)

    async def update(
        self,
        tenant_id: UUID,
        route_id: UUID,
        data: UpdateInboundRouteRequest,
    ) -> InboundRoute:
        route = await self._routes.get(tenant_id, route_id)
        if route is None:
            raise InboundRouteNotFoundError
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(route, field, value)
        try:
            await self._routes.flush()
            await self._routes.refresh(route)
        except IntegrityError as error:
            raise InboundRouteDidConflictError from error
        return route

    async def delete(self, tenant_id: UUID, route_id: UUID) -> None:
        route = await self._routes.get(tenant_id, route_id)
        if route is None:
            raise InboundRouteNotFoundError
        await self._routes.delete(route)

    async def resolve(
        self,
        normalized_did: str,
    ) -> tuple[Tenant, TenantConfigRevision]:
        resolution = await self._routes.resolve(normalized_did)
        if resolution is None:
            raise InboundRouteUnavailableError
        return resolution


class PromptCompositionUseCases:
    """Explicit artifact lifecycles; the small generic helpers stay private."""

    def __init__(
        self,
        tenants: TenantRepository,
        revisions: PromptCompositionRepository,
        configs: ConfigRevisionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions
        self._configs = configs

    async def create_system_draft(
        self, data: CreatePlatformPromptDraftRequest
    ) -> SystemPromptRevision:
        prompt = await self._revisions.system_prompt(data.key)
        if prompt is None:
            prompt = await self._revisions.add(SystemPrompt(key=data.key))
        return await self._create_text_draft(
            SystemPromptRevision, "system_prompt_id", prompt.id, data.text
        )

    async def create_profile_draft(
        self, data: CreatePlatformPromptDraftRequest
    ) -> ProfilePromptRevision:
        prompt = await self._revisions.profile_prompt(data.key)
        if prompt is None:
            prompt = await self._revisions.add(ProfilePrompt(key=data.key))
        return await self._create_text_draft(
            ProfilePromptRevision, "profile_prompt_id", prompt.id, data.text
        )

    async def create_tenant_prompt_draft(
        self, tenant_id: UUID, data: CreateTextDraftRequest
    ) -> TenantPromptRevision:
        await self._tenant(tenant_id)
        prompt = await self._revisions.tenant_prompt(tenant_id)
        if prompt is None:
            prompt = await self._revisions.add(TenantPrompt(tenant_id=tenant_id))
        return await self._create_text_draft(
            TenantPromptRevision,
            "tenant_prompt_id",
            prompt.id,
            data.text,
            tenant_id=tenant_id,
        )

    async def update_system_draft(
        self, revision_id: UUID, data: UpdateTextDraftRequest, expected_version: int
    ) -> SystemPromptRevision:
        return await self._update_text_draft(
            SystemPromptRevision, revision_id, data.text, expected_version
        )

    async def update_profile_draft(
        self, revision_id: UUID, data: UpdateTextDraftRequest, expected_version: int
    ) -> ProfilePromptRevision:
        return await self._update_text_draft(
            ProfilePromptRevision, revision_id, data.text, expected_version
        )

    async def update_tenant_prompt_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdateTextDraftRequest,
        expected_version: int,
    ) -> TenantPromptRevision:
        return await self._update_text_draft(
            TenantPromptRevision, revision_id, data.text, expected_version, tenant_id
        )

    async def publish_system(
        self, revision_id: UUID
    ) -> tuple[SystemPromptRevision, int, int]:
        revision = await self._publish_text(SystemPromptRevision, revision_id)
        prompt = await self._revisions.system_prompt_by_id(revision.system_prompt_id)
        if prompt is None:
            raise PromptRevisionNotFoundError
        if prompt.key != SYSTEM_PROMPT_KEY:
            return revision, 0, 0
        updated, unchanged = await self._rollout_component(
            "system_prompt_revision_id", revision.id
        )
        return revision, updated, unchanged

    async def publish_profile(
        self, revision_id: UUID
    ) -> tuple[ProfilePromptRevision, int, int]:
        revision = await self._publish_text(ProfilePromptRevision, revision_id)
        profile = await self._revisions.profile_prompt_by_id(revision.profile_prompt_id)
        if profile is None:
            raise PromptRevisionNotFoundError
        updated, unchanged = await self._rollout_component(
            "profile_prompt_revision_id", revision.id, profile_key=profile.key
        )
        return revision, updated, unchanged

    async def publish_tenant_prompt(
        self, tenant_id: UUID, revision_id: UUID
    ) -> TenantPromptRevision:
        return await self._publish_text(TenantPromptRevision, revision_id, tenant_id)

    async def knowledge_base_state(self, tenant_id: UUID) -> KnowledgeBaseStateResponse:
        await self._tenant(tenant_id)
        base = await self._revisions.knowledge_base(tenant_id)
        if base is None:
            return KnowledgeBaseStateResponse(
                tenant_id=tenant_id,
                latest_published_revision=None,
                draft_revision=None,
                published_documents=[],
            )
        published = await self._revisions.latest_published_revision(
            KnowledgeBaseRevision, "knowledge_base_id", base.id
        )
        drafts = await self._revisions.revision_by_parent(
            KnowledgeBaseRevision,
            "knowledge_base_id",
            base.id,
            status=PromptRevisionStatus.DRAFT,
        )
        published_snapshot = (
            await self._knowledge_snapshot_response(published)
            if published is not None
            else None
        )
        return KnowledgeBaseStateResponse(
            tenant_id=tenant_id,
            latest_published_revision=(
                published_snapshot.revision if published_snapshot else None
            ),
            draft_revision=(
                (await self._knowledge_revision_response(drafts[0])) if drafts else None
            ),
            published_documents=(
                [
                    KnowledgeDocumentSummaryResponse(
                        key=document.key,
                        media_type=document_revision.media_type,
                        document_revision_number=document_revision.revision_number,
                        position=link.position,
                    )
                    for link, document, document_revision in (
                        await self._revisions.knowledge_snapshot(
                            tenant_id, published.id
                        )
                    )
                ]
                if published is not None
                else []
            ),
        )

    async def knowledge_base_history(
        self, tenant_id: UUID
    ) -> list[KnowledgeBaseRevisionResponse]:
        await self._tenant(tenant_id)
        base = await self._revisions.knowledge_base(tenant_id)
        if base is None:
            return []
        revisions = await self._revisions.revision_by_parent(
            KnowledgeBaseRevision, "knowledge_base_id", base.id
        )
        return [await self._knowledge_revision_response(item) for item in revisions]

    async def published_knowledge_base(
        self, tenant_id: UUID
    ) -> KnowledgeBaseSnapshotResponse:
        await self._tenant(tenant_id)
        base = await self._revisions.knowledge_base(tenant_id)
        revision = (
            await self._revisions.latest_published_revision(
                KnowledgeBaseRevision, "knowledge_base_id", base.id
            )
            if base is not None
            else None
        )
        if revision is None:
            raise PromptRevisionNotFoundError
        return await self._knowledge_snapshot_response(revision)

    async def plan_knowledge_base(
        self, tenant_id: UUID, data: KnowledgeDocumentsRequest
    ) -> KnowledgeBasePlanResponse:
        await self._tenant(tenant_id)
        base = await self._revisions.knowledge_base(tenant_id)
        current = await self._current_knowledge_revision(base)
        return await self._knowledge_plan(tenant_id, current, data)

    async def push_knowledge_base(
        self,
        tenant_id: UUID,
        data: KnowledgeDocumentsRequest,
        expected_version: int,
    ) -> KnowledgeBasePushResponse:
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        base = await self._revisions.knowledge_base_for_update(tenant_id)
        current = await self._current_knowledge_revision(base)
        if (current.version if current is not None else 0) != expected_version:
            raise PromptRevisionVersionConflictError
        plan = await self._knowledge_plan(tenant_id, current, data)
        if plan.status == "unchanged":
            return KnowledgeBasePushResponse(
                changed=False,
                draft=(
                    await self._knowledge_snapshot_response(current)
                    if current is not None
                    and current.status is PromptRevisionStatus.DRAFT
                    else None
                ),
            )
        if base is None:
            base = await self._revisions.add(KnowledgeBase(tenant_id=tenant_id))

        current_rows = (
            await self._revisions.knowledge_snapshot(tenant_id, current.id)
            if current is not None
            else []
        )
        current_by_key = {
            document.key: document_revision
            for _, document, document_revision in current_rows
        }
        documents = {
            document.key: document
            for document in await self._revisions.knowledge_documents(base.id)
        }
        resolved: list[tuple[KnowledgeDocument, KnowledgeDocumentRevision]] = []
        for desired in sorted(data.documents, key=lambda item: item.key):
            document = documents.get(desired.key)
            if document is None:
                document = await self._revisions.add(
                    KnowledgeDocument(
                        knowledge_base_id=base.id,
                        tenant_id=tenant_id,
                        key=desired.key,
                    )
                )
                documents[desired.key] = document
            existing = current_by_key.get(desired.key)
            if existing is not None and knowledge_content_matches(
                existing.content, desired.content
            ):
                document_revision = existing
            else:
                content_hash = knowledge_content_hash(desired.content)
                matched = await self._revisions.matching_document_revision(
                    document.id, content_hash, desired.content
                )
                if matched is None:
                    matched = await self._revisions.add(
                        KnowledgeDocumentRevision(
                            knowledge_document_id=document.id,
                            knowledge_base_id=base.id,
                            tenant_id=tenant_id,
                            revision_number=await self._revisions.next_document_revision_number(
                                document.id
                            ),
                            media_type=desired.media_type,
                            content=desired.content,
                            content_hash=content_hash,
                        )
                    )
                document_revision = matched
            resolved.append((document, document_revision))

        if current is not None and current.status is PromptRevisionStatus.DRAFT:
            draft = current
            draft.version += 1
        else:
            draft = await self._revisions.add(
                KnowledgeBaseRevision(
                    knowledge_base_id=base.id,
                    tenant_id=tenant_id,
                    revision_number=await self._revisions.next_revision_number(
                        KnowledgeBaseRevision, "knowledge_base_id", base.id
                    ),
                    version=expected_version + 1,
                )
            )
        await self._revisions.replace_knowledge_snapshot(
            draft.id,
            [
                KnowledgeBaseRevisionDocument(
                    knowledge_base_revision_id=draft.id,
                    knowledge_document_revision_id=document_revision.id,
                    tenant_id=tenant_id,
                    knowledge_base_id=base.id,
                    knowledge_document_id=document.id,
                    position=position,
                )
                for position, (document, document_revision) in enumerate(resolved)
            ],
        )
        return KnowledgeBasePushResponse(
            changed=True, draft=await self._knowledge_snapshot_response(draft)
        )

    async def publish_knowledge_base(
        self, tenant_id: UUID
    ) -> KnowledgeBasePublishResponse:
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        base = await self._revisions.knowledge_base_for_update(tenant_id)
        drafts = (
            await self._revisions.revision_by_parent(
                KnowledgeBaseRevision,
                "knowledge_base_id",
                base.id,
                status=PromptRevisionStatus.DRAFT,
            )
            if base is not None
            else []
        )
        if not drafts:
            raise PromptRevisionNotFoundError
        draft = drafts[0]
        draft.status = PromptRevisionStatus.PUBLISHED
        draft.published_at = datetime.now(UTC)
        draft.version += 1
        await self._revisions.flush()
        return KnowledgeBasePublishResponse(
            published=await self._knowledge_snapshot_response(draft)
        )

    async def create_prompt_set_draft(
        self, tenant_id: UUID, data: CreatePromptSetDraftRequest
    ) -> PromptSetRevision:
        await self._tenant(tenant_id)
        prompt_set = await self._revisions.prompt_set(tenant_id)
        if prompt_set is None:
            prompt_set = await self._revisions.add(PromptSet(tenant_id=tenant_id))
        existing = await self._revisions.revision_by_parent(
            PromptSetRevision,
            "prompt_set_id",
            prompt_set.id,
            status=PromptRevisionStatus.DRAFT,
        )
        if existing:
            raise PromptRevisionActiveDraftExistsError
        return await self._revisions.add(
            PromptSetRevision(
                prompt_set_id=prompt_set.id,
                tenant_id=tenant_id,
                revision_number=await self._revisions.next_revision_number(
                    PromptSetRevision, "prompt_set_id", prompt_set.id
                ),
                **data.model_dump(),
            )
        )

    async def update_prompt_set_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdatePromptSetDraftRequest,
        expected_version: int,
    ) -> PromptSetRevision:
        revision = await self._prompt_set_for_update(tenant_id, revision_id)
        if revision.status is not PromptRevisionStatus.DRAFT:
            raise PromptRevisionImmutableError
        if revision.version != expected_version:
            raise PromptRevisionVersionConflictError
        for field, value in data.model_dump().items():
            setattr(revision, field, value)
        revision.version += 1
        await self._revisions.flush()
        return revision

    async def validate_prompt_set_draft(
        self, tenant_id: UUID, revision_id: UUID
    ) -> list[ValidationIssue]:
        revision = await self._prompt_set(tenant_id, revision_id)
        if revision.status is not PromptRevisionStatus.DRAFT:
            raise PromptRevisionImmutableError
        return await self._validate_prompt_set(tenant_id, revision)

    async def publish_prompt_set(
        self, tenant_id: UUID, revision_id: UUID
    ) -> PromptSetRevision:
        tenant = await self._tenant(tenant_id)
        revision = await self._prompt_set_for_update(tenant_id, revision_id)
        if revision.status is not PromptRevisionStatus.DRAFT:
            raise PromptRevisionImmutableError
        errors = await self._validate_prompt_set(tenant_id, revision)
        if errors:
            raise InvalidPromptSetError
        if tenant.active_prompt_set_revision_id:
            active = await self._prompt_set_for_update(
                tenant_id, tenant.active_prompt_set_revision_id
            )
            active.status = PromptRevisionStatus.ARCHIVED
        revision.status = PromptRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        tenant.active_prompt_set_revision_id = revision.id
        await self._revisions.flush()
        return revision

    async def list_system(self, key: str) -> list[SystemPromptRevision]:
        prompt = await self._revisions.system_prompt(key)
        return (
            []
            if prompt is None
            else await self._revisions.revision_by_parent(
                SystemPromptRevision, "system_prompt_id", prompt.id
            )
        )

    async def list_profiles(self) -> list[ProfilePrompt]:
        return await self._revisions.list_profile_prompts()

    async def list_profile(self, key: str) -> list[ProfilePromptRevision]:
        prompt = await self._revisions.profile_prompt(key)
        return (
            []
            if prompt is None
            else await self._revisions.revision_by_parent(
                ProfilePromptRevision, "profile_prompt_id", prompt.id
            )
        )

    async def list_tenant_prompts(self, tenant_id: UUID) -> list[TenantPromptRevision]:
        prompt = await self._revisions.tenant_prompt(tenant_id)
        return (
            []
            if prompt is None
            else await self._revisions.revision_by_parent(
                TenantPromptRevision, "tenant_prompt_id", prompt.id
            )
        )

    async def list_knowledge_bases(
        self, tenant_id: UUID
    ) -> list[KnowledgeBaseRevision]:
        base = await self._revisions.knowledge_base(tenant_id)
        return (
            []
            if base is None
            else await self._revisions.revision_by_parent(
                KnowledgeBaseRevision, "knowledge_base_id", base.id
            )
        )

    async def list_prompt_sets(self, tenant_id: UUID) -> list[PromptSetRevision]:
        prompt_set = await self._revisions.prompt_set(tenant_id)
        return (
            []
            if prompt_set is None
            else await self._revisions.revision_by_parent(
                PromptSetRevision, "prompt_set_id", prompt_set.id
            )
        )

    async def active_prompt_set(self, tenant_id: UUID) -> PromptSetRevision:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        if tenant.active_prompt_set_revision_id is None:
            raise PromptRevisionNotFoundError
        return await self._prompt_set(tenant_id, tenant.active_prompt_set_revision_id)

    async def prompt_set_detail(self, tenant_id: UUID) -> PromptSetDetailResponse:
        revision = await self.active_prompt_set(tenant_id)
        return await self._prompt_set_detail(revision)

    async def prompt_set_history(
        self, tenant_id: UUID
    ) -> list[PromptSetDetailResponse]:
        return [
            await self._prompt_set_detail(revision)
            for revision in await self.list_prompt_sets(tenant_id)
            if revision.status is not PromptRevisionStatus.DRAFT
        ]

    async def plan_prompt_set(self, tenant_id: UUID) -> PromptSetPlanResponse:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        desired = await self._desired_composition(tenant)
        active = (
            None
            if tenant.active_prompt_set_revision_id is None
            else await self._prompt_set(tenant_id, tenant.active_prompt_set_revision_id)
        )
        return await self._prompt_set_plan(tenant, active, desired)

    async def apply_prompt_set(self, tenant_id: UUID) -> PromptSetApplyResponse:
        tenant = await self._tenant(tenant_id)
        desired = await self._desired_composition(tenant)
        active = (
            None
            if tenant.active_prompt_set_revision_id is None
            else await self._prompt_set_for_update(
                tenant_id, tenant.active_prompt_set_revision_id
            )
        )
        revision, changed = await self._activate_composition(
            tenant, active, desired, validate_profile=True
        )
        return PromptSetApplyResponse(
            changed=changed,
            prompt_set=await self._prompt_set_detail(revision),
        )

    async def _rollout_component(
        self,
        field: str,
        revision_id: UUID,
        *,
        profile_key: str | None = None,
    ) -> tuple[int, int]:
        updated = unchanged = 0
        for tenant in await self._tenants.list_prompt_rollout_targets_for_update():
            if profile_key is not None:
                config = await self._active_v3_config(tenant, required=False)
                if config is None or config.agent.profile != profile_key:
                    continue
            assert tenant.active_prompt_set_revision_id is not None
            active = await self._prompt_set_for_update(
                tenant.id, tenant.active_prompt_set_revision_id
            )
            if getattr(active, field) == revision_id:
                unchanged += 1
                continue
            composition = {
                "system_prompt_revision_id": active.system_prompt_revision_id,
                "profile_prompt_revision_id": active.profile_prompt_revision_id,
                "tenant_prompt_revision_id": active.tenant_prompt_revision_id,
                "knowledge_base_revision_id": active.knowledge_base_revision_id,
            }
            composition[field] = revision_id
            _, changed = await self._activate_composition(
                tenant,
                active,
                composition,
                validate_profile=profile_key is not None,
            )
            updated += int(changed)
            unchanged += int(not changed)
        return updated, unchanged

    async def _desired_composition(self, tenant: Tenant) -> dict[str, UUID]:
        config = await self._active_v3_config(tenant, required=True)
        assert config is not None
        system = await self._required_latest(
            await self._revisions.system_prompt(SYSTEM_PROMPT_KEY),
            SystemPromptRevision,
            "system_prompt_id",
            "system_prompt",
            f"SystemPrompt '{SYSTEM_PROMPT_KEY}'",
        )
        profile = await self._required_latest(
            await self._revisions.profile_prompt(config.agent.profile),
            ProfilePromptRevision,
            "profile_prompt_id",
            "profile_prompt",
            f"ProfilePrompt '{config.agent.profile}'",
        )
        tenant_prompt = await self._required_latest(
            await self._revisions.tenant_prompt(tenant.id),
            TenantPromptRevision,
            "tenant_prompt_id",
            "tenant_prompt",
            "TenantPrompt",
        )
        knowledge = await self._required_latest(
            await self._revisions.knowledge_base(tenant.id),
            KnowledgeBaseRevision,
            "knowledge_base_id",
            "knowledge_base",
            "KnowledgeBase",
        )
        return {
            "system_prompt_revision_id": system.id,
            "profile_prompt_revision_id": profile.id,
            "tenant_prompt_revision_id": tenant_prompt.id,
            "knowledge_base_revision_id": knowledge.id,
        }

    async def _required_latest(
        self,
        parent: Any | None,
        revision_type: type[Any],
        parent_field: str,
        path: str,
        label: str,
    ) -> Any:
        if parent is None:
            raise PromptSetResolutionError(
                path, "artifact_not_found", f"{label} does not exist"
            )
        revision = await self._revisions.latest_published_revision(
            revision_type, parent_field, parent.id
        )
        if revision is None:
            raise PromptSetResolutionError(
                path,
                "published_revision_not_found",
                f"{label} has no published revision",
            )
        return revision

    async def _active_v3_config(
        self, tenant: Tenant, *, required: bool
    ) -> TenantConfigV3 | None:
        if tenant.active_config_revision_id is None:
            if required:
                raise PromptSetResolutionError(
                    "tenant.active_config_revision_id",
                    "active_config_not_found",
                    "tenant has no active config",
                )
            return None
        revision = await self._configs.get(tenant.id, tenant.active_config_revision_id)
        if revision is None or revision.schema_version not in {3, 4}:
            if required:
                raise PromptSetResolutionError(
                    "tenant.active_config_revision",
                    "active_config_not_v3",
                    "active config is not TenantConfigV3",
                )
            return None
        try:
            model = TENANT_CONFIG_SCHEMAS[revision.schema_version]
            config = model.model_validate(revision.config)
            assert isinstance(config, TenantConfigV3)
            return config
        except ValidationError as error:
            raise PromptSetResolutionError(
                "tenant.active_config_revision",
                "active_config_invalid",
                "active TenantConfigV3 is invalid",
            ) from error

    async def _activate_composition(
        self,
        tenant: Tenant,
        active: PromptSetRevision | None,
        composition: dict[str, UUID],
        *,
        validate_profile: bool,
    ) -> tuple[PromptSetRevision, bool]:
        if active is not None and all(
            getattr(active, field) == value for field, value in composition.items()
        ):
            return active, False
        candidate = PromptSetRevision(
            tenant_id=tenant.id,
            prompt_set_id=active.prompt_set_id if active is not None else UUID(int=0),
            revision_number=0,
            **composition,
        )
        errors = await self._validate_prompt_set(
            tenant.id, candidate, validate_profile=validate_profile
        )
        if errors:
            raise InvalidPromptSetError
        prompt_set = await self._revisions.prompt_set(tenant.id)
        if prompt_set is None:
            prompt_set = await self._revisions.add(PromptSet(tenant_id=tenant.id))
        revision = await self._revisions.add(
            PromptSetRevision(
                prompt_set_id=prompt_set.id,
                tenant_id=tenant.id,
                revision_number=await self._revisions.next_revision_number(
                    PromptSetRevision, "prompt_set_id", prompt_set.id
                ),
                status=PromptRevisionStatus.PUBLISHED,
                published_at=datetime.now(UTC),
                **composition,
            )
        )
        if active is not None and active.id != revision.id:
            active.status = PromptRevisionStatus.ARCHIVED
        tenant.active_prompt_set_revision_id = revision.id
        await self._revisions.flush()
        return revision, True

    async def _prompt_set_plan(
        self,
        tenant: Tenant,
        active: PromptSetRevision | None,
        desired: dict[str, UUID],
    ) -> PromptSetPlanResponse:
        desired_detail = await self._composition_detail(tenant.id, desired)
        active_detail = (
            None
            if active is None
            else await self._composition_detail(
                tenant.id,
                {
                    "system_prompt_revision_id": active.system_prompt_revision_id,
                    "profile_prompt_revision_id": active.profile_prompt_revision_id,
                    "tenant_prompt_revision_id": active.tenant_prompt_revision_id,
                    "knowledge_base_revision_id": active.knowledge_base_revision_id,
                },
            )
        )
        reasons = {
            "system": "platform current revision differs",
            "profile": (f"active TenantConfig selects {desired_detail.profile.key}"),
            "tenant_prompt": "newer published tenant revision available",
            "knowledge_base": "newer published KnowledgeBase revision available",
        }

        def component(name: str) -> PromptSetComponentPlanResponse:
            current = None if active_detail is None else getattr(active_detail, name)
            target = getattr(desired_detail, name)
            changed = current is None or current.revision_id != target.revision_id
            return PromptSetComponentPlanResponse(
                active=current,
                desired=target,
                changed=changed,
                reason=reasons[name] if changed else None,
            )

        components = PromptSetPlanComponentsResponse(
            system=component("system"),
            profile=component("profile"),
            tenant_prompt=component("tenant_prompt"),
            knowledge_base=component("knowledge_base"),
        )
        changed = any(
            item.changed
            for item in (
                components.system,
                components.profile,
                components.tenant_prompt,
                components.knowledge_base,
            )
        )
        return PromptSetPlanResponse(
            tenant_id=tenant.id,
            status=(
                "missing-active"
                if active is None
                else "modified"
                if changed
                else "unchanged"
            ),
            active_revision_number=None if active is None else active.revision_number,
            components=components,
        )

    async def _prompt_set_detail(
        self, revision: PromptSetRevision
    ) -> PromptSetDetailResponse:
        return PromptSetDetailResponse(
            revision=PromptSetRevisionResponse.model_validate(revision),
            components=await self._composition_detail(
                revision.tenant_id,
                {
                    "system_prompt_revision_id": revision.system_prompt_revision_id,
                    "profile_prompt_revision_id": revision.profile_prompt_revision_id,
                    "tenant_prompt_revision_id": revision.tenant_prompt_revision_id,
                    "knowledge_base_revision_id": revision.knowledge_base_revision_id,
                },
            ),
        )

    async def _composition_detail(
        self, tenant_id: UUID, composition: dict[str, UUID]
    ) -> PromptSetCompositionResponse:
        system = await self._revisions.revision(
            SystemPromptRevision, composition["system_prompt_revision_id"]
        )
        profile = await self._revisions.revision(
            ProfilePromptRevision, composition["profile_prompt_revision_id"]
        )
        tenant_prompt = await self._revisions.revision(
            TenantPromptRevision,
            composition["tenant_prompt_revision_id"],
            tenant_id=tenant_id,
        )
        knowledge = await self._revisions.revision(
            KnowledgeBaseRevision,
            composition["knowledge_base_revision_id"],
            tenant_id=tenant_id,
        )
        if any(item is None for item in (system, profile, tenant_prompt, knowledge)):
            raise PromptSetResolutionError(
                "active_prompt_set",
                "component_not_found",
                "PromptSet contains an unavailable component revision",
            )
        assert system is not None
        assert profile is not None
        assert tenant_prompt is not None
        assert knowledge is not None
        system_parent = await self._revisions.system_prompt_by_id(
            system.system_prompt_id
        )
        profile_parent = await self._revisions.profile_prompt_by_id(
            profile.profile_prompt_id
        )
        if system_parent is None or profile_parent is None:
            raise PromptSetResolutionError(
                "active_prompt_set",
                "component_parent_not_found",
                "PromptSet contains an unavailable platform prompt",
            )
        return PromptSetCompositionResponse(
            system=PromptSetComponentResponse(
                revision_id=system.id,
                revision_number=system.revision_number,
                key=system_parent.key,
            ),
            profile=PromptSetComponentResponse(
                revision_id=profile.id,
                revision_number=profile.revision_number,
                key=profile_parent.key,
            ),
            tenant_prompt=PromptSetComponentResponse(
                revision_id=tenant_prompt.id,
                revision_number=tenant_prompt.revision_number,
            ),
            knowledge_base=PromptSetComponentResponse(
                revision_id=knowledge.id,
                revision_number=knowledge.revision_number,
            ),
        )

    async def _current_knowledge_revision(
        self, base: KnowledgeBase | None
    ) -> KnowledgeBaseRevision | None:
        if base is None:
            return None
        drafts = await self._revisions.revision_by_parent(
            KnowledgeBaseRevision,
            "knowledge_base_id",
            base.id,
            status=PromptRevisionStatus.DRAFT,
        )
        if drafts:
            return drafts[0]
        return await self._revisions.latest_published_revision(
            KnowledgeBaseRevision, "knowledge_base_id", base.id
        )

    async def _knowledge_plan(
        self,
        tenant_id: UUID,
        current: KnowledgeBaseRevision | None,
        data: KnowledgeDocumentsRequest,
    ) -> KnowledgeBasePlanResponse:
        rows = (
            await self._revisions.knowledge_snapshot(tenant_id, current.id)
            if current is not None
            else []
        )
        remote = {
            document.key: document_revision for _, document, document_revision in rows
        }
        desired = {document.key: document for document in data.documents}
        documents: list[KnowledgeDocumentPlanResponse] = []
        for key in sorted(remote.keys() | desired.keys()):
            local = desired.get(key)
            existing = remote.get(key)
            status: Literal["unchanged", "modified", "local-only", "missing-local"]
            action: Literal["reuse", "create", "remove"]
            if local is None:
                status, action = "missing-local", "remove"
            elif existing is None:
                status, action = "local-only", "create"
            elif knowledge_content_matches(existing.content, local.content):
                status, action = "unchanged", "reuse"
            else:
                status, action = "modified", "create"
            documents.append(
                KnowledgeDocumentPlanResponse(
                    key=key,
                    status=status,
                    current_revision_number=(
                        existing.revision_number if existing is not None else None
                    ),
                    action=action,
                )
            )
        reuse_count = sum(item.action == "reuse" for item in documents)
        create_count = sum(item.action == "create" for item in documents)
        remove_count = sum(item.action == "remove" for item in documents)
        return KnowledgeBasePlanResponse(
            tenant_id=tenant_id,
            status=("modified" if create_count or remove_count else "unchanged"),
            base_version=current.version if current is not None else 0,
            documents=documents,
            reuse_count=reuse_count,
            create_count=create_count,
            remove_count=remove_count,
            update_draft=bool(create_count or remove_count),
        )

    async def _knowledge_revision_response(
        self, revision: KnowledgeBaseRevision
    ) -> KnowledgeBaseRevisionResponse:
        rows = await self._revisions.knowledge_snapshot(revision.tenant_id, revision.id)
        return KnowledgeBaseRevisionResponse(
            id=revision.id,
            tenant_id=revision.tenant_id,
            knowledge_base_id=revision.knowledge_base_id,
            revision_number=revision.revision_number,
            status=revision.status,
            created_at=revision.created_at,
            published_at=revision.published_at,
            version=revision.version,
            document_count=len(rows),
        )

    async def _knowledge_snapshot_response(
        self, revision: KnowledgeBaseRevision
    ) -> KnowledgeBaseSnapshotResponse:
        rows = await self._revisions.knowledge_snapshot(revision.tenant_id, revision.id)
        return KnowledgeBaseSnapshotResponse(
            revision=KnowledgeBaseRevisionResponse(
                id=revision.id,
                tenant_id=revision.tenant_id,
                knowledge_base_id=revision.knowledge_base_id,
                revision_number=revision.revision_number,
                status=revision.status,
                created_at=revision.created_at,
                published_at=revision.published_at,
                version=revision.version,
                document_count=len(rows),
            ),
            documents=[
                KnowledgeDocumentRevisionResponse(
                    key=document.key,
                    media_type=document_revision.media_type,
                    document_revision_number=document_revision.revision_number,
                    content=document_revision.content,
                    content_hash=document_revision.content_hash,
                    position=link.position,
                )
                for link, document, document_revision in rows
            ],
        )

    async def _create_text_draft(
        self,
        revision_type: type[Any],
        parent_field: str,
        parent_id: UUID,
        text: str,
        *,
        tenant_id: UUID | None = None,
    ) -> Any:
        existing = await self._revisions.revision_by_parent(
            revision_type, parent_field, parent_id, status=PromptRevisionStatus.DRAFT
        )
        if existing:
            raise PromptRevisionActiveDraftExistsError
        values: dict[str, object] = {
            parent_field: parent_id,
            "revision_number": await self._revisions.next_revision_number(
                revision_type, parent_field, parent_id
            ),
            "text": text,
        }
        if tenant_id is not None:
            values["tenant_id"] = tenant_id
        return await self._revisions.add(revision_type(**values))

    async def _update_text_draft(
        self,
        revision_type: type[Any],
        revision_id: UUID,
        value: str,
        expected_version: int,
        tenant_id: UUID | None = None,
    ) -> Any:
        revision = await self._revisions.revision(
            revision_type, revision_id, tenant_id=tenant_id, lock=True
        )
        if revision is None:
            raise PromptRevisionNotFoundError
        if revision.status is not PromptRevisionStatus.DRAFT:
            raise PromptRevisionImmutableError
        if revision.version != expected_version:
            raise PromptRevisionVersionConflictError
        revision.text = value
        revision.version += 1
        await self._revisions.flush()
        return revision

    async def _publish_text(
        self,
        revision_type: type[Any],
        revision_id: UUID,
        tenant_id: UUID | None = None,
    ) -> Any:
        revision = await self._revisions.revision(
            revision_type, revision_id, tenant_id=tenant_id, lock=True
        )
        if revision is None:
            raise PromptRevisionNotFoundError
        if revision.status is not PromptRevisionStatus.DRAFT:
            raise PromptRevisionImmutableError
        revision.status = PromptRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        await self._revisions.flush()
        return revision

    async def _validate_prompt_set(
        self,
        tenant_id: UUID,
        revision: PromptSetRevision,
        *,
        validate_profile: bool = True,
    ) -> list[ValidationIssue]:
        sources = (
            (
                "system_prompt_revision_id",
                SystemPromptRevision,
                None,
                revision.system_prompt_revision_id,
            ),
            (
                "profile_prompt_revision_id",
                ProfilePromptRevision,
                None,
                revision.profile_prompt_revision_id,
            ),
            (
                "tenant_prompt_revision_id",
                TenantPromptRevision,
                tenant_id,
                revision.tenant_prompt_revision_id,
            ),
            (
                "knowledge_base_revision_id",
                KnowledgeBaseRevision,
                tenant_id,
                revision.knowledge_base_revision_id,
            ),
        )
        errors: list[ValidationIssue] = []
        for field, revision_type, owner, artifact_id in sources:
            artifact = await self._revisions.revision(
                revision_type, artifact_id, tenant_id=owner
            )
            if artifact is None:
                errors.append(
                    ValidationIssue(
                        path=field,
                        code="revision_not_found",
                        message="revision does not belong to this owner",
                    )
                )
            elif artifact.status is not PromptRevisionStatus.PUBLISHED:
                errors.append(
                    ValidationIssue(
                        path=field,
                        code="revision_not_published",
                        message="PromptSet references must be published",
                    )
                )
        tenant = await self._tenants.get(tenant_id)
        if (
            validate_profile
            and tenant is not None
            and tenant.active_config_revision_id is not None
        ):
            config_revision = await self._configs.get(
                tenant_id, tenant.active_config_revision_id
            )
            if config_revision is not None and config_revision.schema_version in {3, 4}:
                model = TENANT_CONFIG_SCHEMAS[config_revision.schema_version]
                config = model.model_validate(config_revision.config)
                assert isinstance(config, TenantConfigV3)
                profile_revision = await self._revisions.revision(
                    ProfilePromptRevision, revision.profile_prompt_revision_id
                )
                if profile_revision is not None:
                    profile = await self._revisions.profile_prompt_by_id(
                        profile_revision.profile_prompt_id
                    )
                    if profile is None or profile.key != config.agent.profile:
                        errors.append(
                            ValidationIssue(
                                path="profile_prompt_revision_id",
                                code="profile_mismatch",
                                message="PromptSet profile must match active TenantConfigV3",
                            )
                        )
        return errors

    async def _tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def _prompt_set(
        self, tenant_id: UUID, revision_id: UUID
    ) -> PromptSetRevision:
        revision = await self._revisions.revision(
            PromptSetRevision, revision_id, tenant_id=tenant_id
        )
        if revision is None:
            raise PromptRevisionNotFoundError
        return revision

    async def _prompt_set_for_update(
        self, tenant_id: UUID, revision_id: UUID
    ) -> PromptSetRevision:
        revision = await self._revisions.revision(
            PromptSetRevision, revision_id, tenant_id=tenant_id, lock=True
        )
        if revision is None:
            raise PromptRevisionNotFoundError
        return revision


class ConfigUseCases:
    def __init__(
        self,
        tenants: TenantRepository,
        revisions: ConfigRevisionRepository,
        connections: IntegrationConnectionRepository,
        prompts: PromptCompositionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions
        self._connections = connections
        self._prompts = prompts

    async def create_config_draft(
        self,
        tenant_id: UUID,
        data: CreateDraftRequest,
    ) -> TenantConfigRevision:
        tenant = await self._tenant_for_update(tenant_id)
        await self._ensure_no_draft(tenant_id)

        config = data.config
        schema_version = data.schema_version
        if config is None and tenant.active_config_revision_id:
            source = await self._revision(
                tenant_id,
                tenant.active_config_revision_id,
            )
            config = deepcopy(source.config)
            schema_version = schema_version or source.schema_version

        config = config or {}
        if schema_version is None:
            config_schema_version = config.get("schema_version")
            schema_version = (
                config_schema_version
                if type(config_schema_version) is int and config_schema_version > 0
                else 3
            )

        revision = TenantConfigRevision(
            tenant_id=tenant_id,
            revision_number=await self._revisions.next_revision_number(tenant_id),
            schema_version=schema_version,
            config=config,
            created_by=None,
            comment=data.comment,
        )
        try:
            return await self._revisions.add(revision)
        except IntegrityError as error:
            raise ActiveDraftExistsError from error

    async def update_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdateDraftRequest,
        expected_version: int,
    ) -> TenantConfigRevision:
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        if revision.version != expected_version:
            raise ConfigRevisionVersionConflictError

        changes = data.model_dump(exclude_unset=True)
        if "config" in changes and "schema_version" not in changes:
            config_schema_version = changes["config"].get("schema_version")
            if type(config_schema_version) is int and config_schema_version > 0:
                changes["schema_version"] = config_schema_version

        for field, value in changes.items():
            setattr(revision, field, value)
        revision.version += 1
        await self._revisions.flush()
        return revision

    async def get_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revision(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        return revision

    async def validate_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> list[ValidationIssue]:
        revision = await self._revision(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        _, errors = await self._validate_config(revision)
        return errors

    async def validate_config(
        self,
        tenant_id: UUID,
        data: ValidateConfigRequest,
    ) -> tuple[TenantConfig | None, list[ValidationIssue]]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        revision = TenantConfigRevision(
            tenant_id=tenant_id,
            revision_number=1,
            schema_version=data.schema_version,
            config=data.config,
        )
        return await self._validate_config(revision)

    async def publish_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        tenant = await self._tenant_for_update(tenant_id)
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        _, errors = await self._validate_config(revision)
        if errors:
            raise InvalidTenantConfigError([error.model_dump() for error in errors])

        if tenant.active_config_revision_id:
            active = await self._revision_for_update(
                tenant_id,
                tenant.active_config_revision_id,
            )
            active.status = ConfigRevisionStatus.ARCHIVED

        revision.status = ConfigRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        tenant.active_config_revision_id = revision.id
        await self._revisions.flush()
        return revision

    async def list_config_revisions(
        self,
        tenant_id: UUID,
    ) -> list[TenantConfigRevision]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._revisions.list(tenant_id)

    async def get_active_config(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def get_internal_active_config(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None or not tenant.is_available_in_runtime:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def _active_config(
        self,
        tenant: Tenant,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        if tenant.active_config_revision_id is None:
            raise ActiveConfigNotFoundError

        revision = await self._revision(
            tenant.id,
            tenant.active_config_revision_id,
        )
        if (
            revision.status is not ConfigRevisionStatus.PUBLISHED
            or revision.published_at is None
        ):
            raise ActiveConfigNotFoundError
        config, errors = await self._validate_config(revision)
        if config is None:
            raise InvalidTenantConfigError([error.model_dump() for error in errors])
        return revision, config

    async def _tenant_for_update(self, tenant_id: UUID) -> Tenant:
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def _revision(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revisions.get(tenant_id, revision_id)
        if revision is None:
            raise ConfigRevisionNotFoundError
        return revision

    async def _revision_for_update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revisions.get_for_update(tenant_id, revision_id)
        if revision is None:
            raise ConfigRevisionNotFoundError
        return revision

    async def _ensure_no_draft(self, tenant_id: UUID) -> None:
        if await self._revisions.get_draft(tenant_id):
            raise ActiveDraftExistsError

    async def _validate_config(
        self,
        revision: TenantConfigRevision,
    ) -> tuple[TenantConfig | None, list[ValidationIssue]]:
        model = TENANT_CONFIG_SCHEMAS.get(revision.schema_version)
        if model is None:
            supported_versions = ", ".join(
                str(version) for version in TENANT_CONFIG_SCHEMAS
            )
            return (
                None,
                [
                    ValidationIssue(
                        path="schema_version",
                        code="unsupported_schema_version",
                        message=(
                            f"Only schema_version {supported_versions} are supported"
                        ),
                    )
                ],
            )
        try:
            config = cast(TenantConfig, model.model_validate(revision.config))
        except ValidationError as error:
            return (
                None,
                [
                    ValidationIssue(
                        path=".".join(str(part) for part in item["loc"]),
                        code=item["type"],
                        message=item["msg"],
                    )
                    for item in error.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    )
                ],
            )
        if isinstance(config, (TenantConfigV2, TenantConfigV3)):
            # V1 only has boolean switches; V2+ can carry capability profiles.
            capability_errors = await self._validate_capabilities(
                revision.tenant_id,
                config,
            )
            if capability_errors:
                return None, capability_errors
        if (
            isinstance(config, TenantConfigV3)
            and await self._prompts.profile_prompt(config.agent.profile) is None
        ):
            return (
                None,
                [
                    ValidationIssue(
                        path="agent.profile",
                        code="profile_not_found",
                        message="ProfilePrompt key does not exist",
                    )
                ],
            )
        return config, []

    async def _validate_capabilities(
        self,
        tenant_id: UUID,
        config: TenantConfigV2 | TenantConfigV3,
    ) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        for semantic_key, raw_profile in config.capabilities.items():
            if not isinstance(raw_profile, TenantCapabilityProfile):
                continue
            path = f"capabilities.{semantic_key}"
            try:
                capability = definition(semantic_key, raw_profile.semantic_version)
                validate_agent_schema(raw_profile.agent_input_schema, capability)
                connection = await self._connections.get(
                    tenant_id,
                    raw_profile.execution.connection_id,
                )
                if connection is None:
                    raise CapabilityValidationError(
                        "connection_not_found",
                        "Connection does not belong to tenant",
                        "execution.connection_id",
                    )
                if connection.status is not IntegrationConnectionStatus.ACTIVE:
                    raise CapabilityValidationError(
                        "connection_disabled",
                        "Connection must be active",
                        "execution.connection_id",
                    )
                if connection.provider is not provider_for_plan_type(
                    raw_profile.execution.plan_type
                ):
                    raise CapabilityValidationError(
                        "connection_provider_mismatch",
                        "Connection provider does not match plan type",
                        "execution.connection_id",
                    )
                for index, fixture in enumerate(raw_profile.validation_fixtures):
                    validate_agent_input(raw_profile.agent_input_schema, fixture)
                    canonical = validate_business_input(
                        normalize_input(raw_profile.agent_input_schema, fixture),
                        config.localization.timezone,
                        enforce_not_past=False,
                    )
                    compile_plan(
                        raw_profile,
                        canonical,
                        operation_id=UUID("00000000-0000-0000-0000-000000000001"),
                        call_id=UUID("00000000-0000-0000-0000-000000000002"),
                        tool_call_id=f"publication-fixture-{index}",
                        credential_ref=connection.credential_ref,
                        caller_phone="+421900000000",
                    )
            except CapabilityValidationError as error:
                errors.append(
                    ValidationIssue(
                        path=f"{path}.{error.path}".rstrip("."),
                        code=error.code,
                        message=error.message,
                    )
                )
        return errors
