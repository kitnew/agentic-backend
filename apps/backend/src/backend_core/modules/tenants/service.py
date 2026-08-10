from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast
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

from backend_core.modules.capabilities.domain import (
    CapabilityValidationError,
    compile_plan,
    definition,
    normalize_input,
    validate_agent_input,
    validate_agent_schema,
    validate_business_input,
)
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
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    KnowledgeBase,
    KnowledgeBaseRevision,
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
    UpdateDraftRequest,
    UpdateInboundRouteRequest,
    UpdatePromptSetDraftRequest,
    UpdateTextDraftRequest,
    ValidateConfigRequest,
    ValidationIssue,
)


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

    async def create_knowledge_base_draft(
        self, tenant_id: UUID, data: CreateTextDraftRequest
    ) -> KnowledgeBaseRevision:
        await self._tenant(tenant_id)
        base = await self._revisions.knowledge_base(tenant_id)
        if base is None:
            base = await self._revisions.add(KnowledgeBase(tenant_id=tenant_id))
        return await self._create_text_draft(
            KnowledgeBaseRevision,
            "knowledge_base_id",
            base.id,
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

    async def update_knowledge_base_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdateTextDraftRequest,
        expected_version: int,
    ) -> KnowledgeBaseRevision:
        return await self._update_text_draft(
            KnowledgeBaseRevision, revision_id, data.text, expected_version, tenant_id
        )

    async def publish_system(self, revision_id: UUID) -> SystemPromptRevision:
        return await self._publish_text(SystemPromptRevision, revision_id)

    async def publish_profile(self, revision_id: UUID) -> ProfilePromptRevision:
        return await self._publish_text(ProfilePromptRevision, revision_id)

    async def publish_tenant_prompt(
        self, tenant_id: UUID, revision_id: UUID
    ) -> TenantPromptRevision:
        return await self._publish_text(TenantPromptRevision, revision_id, tenant_id)

    async def publish_knowledge_base(
        self, tenant_id: UUID, revision_id: UUID
    ) -> KnowledgeBaseRevision:
        return await self._publish_text(KnowledgeBaseRevision, revision_id, tenant_id)

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
        self, tenant_id: UUID, revision: PromptSetRevision
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
        if tenant is not None and tenant.active_config_revision_id is not None:
            config_revision = await self._configs.get(
                tenant_id, tenant.active_config_revision_id
            )
            if config_revision is not None and config_revision.schema_version == 3:
                config = TenantConfigV3.model_validate(config_revision.config)
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
