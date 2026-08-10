from typing import Annotated, Any
from uuid import UUID

from contracts import ActiveTenantConfig
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)

from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotFoundError,
    ConfigRevisionVersionConflictError,
    InboundRouteDidConflictError,
    InboundRouteNotFoundError,
    InboundRouteUnavailableError,
    InvalidTenantConfigError,
    PromptRevisionError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.legacy_yaml import (
    LegacyYamlError,
    parse_legacy_yaml,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptCompositionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    ConfigRevisionResponse,
    CreateDraftRequest,
    CreateInboundRouteRequest,
    CreatePlatformPromptDraftRequest,
    CreatePromptSetDraftRequest,
    CreateTenantRequest,
    CreateTextDraftRequest,
    InboundRouteResponse,
    KnowledgeBaseRevisionResponse,
    LegacyConfigImportResponse,
    PlatformPromptRevisionResponse,
    PromptSetRevisionResponse,
    PromptTextRevisionResponse,
    ResolveTenantRouteRequest,
    Slug,
    TenantPromptRevisionResponse,
    TenantResponse,
    TenantRouteResolutionResponse,
    UpdateDraftRequest,
    UpdateInboundRouteRequest,
    UpdatePromptSetDraftRequest,
    UpdateTextDraftRequest,
    ValidateDraftResponse,
)
from backend_core.modules.tenants.service import (
    ConfigUseCases,
    InboundRouteService,
    PromptCompositionUseCases,
    TenantService,
)
from backend_core.platform.auth import require_admin, require_internal_scope
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants",
    tags=["admin:tenants"],
    dependencies=[Depends(require_admin)],
)
internal_router = APIRouter(
    prefix="/internal/v1",
    tags=["internal:tenants"],
)
platform_router = APIRouter(
    prefix="/admin/v1/platform/prompts",
    tags=["admin:platform-prompts"],
    dependencies=[Depends(require_admin)],
)


def get_tenant_service(session: DatabaseSession) -> TenantService:
    return TenantService(TenantRepository(session))


TenantServiceDependency = Annotated[TenantService, Depends(get_tenant_service)]


def get_config_use_cases(
    session: DatabaseSession,
) -> ConfigUseCases:
    return ConfigUseCases(
        TenantRepository(session),
        ConfigRevisionRepository(session),
        IntegrationConnectionRepository(session),
    )


ConfigUseCasesDependency = Annotated[
    ConfigUseCases,
    Depends(get_config_use_cases),
]


def get_inbound_route_service(
    session: DatabaseSession,
) -> InboundRouteService:
    return InboundRouteService(
        TenantRepository(session),
        InboundRouteRepository(session),
    )


InboundRouteServiceDependency = Annotated[
    InboundRouteService,
    Depends(get_inbound_route_service),
]


def get_prompt_composition_use_cases(
    session: DatabaseSession,
) -> PromptCompositionUseCases:
    return PromptCompositionUseCases(
        TenantRepository(session),
        PromptCompositionRepository(session),
        ConfigRevisionRepository(session),
    )


PromptCompositionUseCasesDependency = Annotated[
    PromptCompositionUseCases,
    Depends(get_prompt_composition_use_cases),
]


def config_http_exception(
    error: TenantNotFoundError | ConfigRevisionError,
) -> HTTPException:
    if isinstance(error, (TenantNotFoundError, ConfigRevisionNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant or config revision not found",
        )
    if isinstance(error, ActiveConfigNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant has no active config",
        )
    if isinstance(error, InvalidTenantConfigError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "invalid tenant config",
                "errors": error.errors,
            },
        )
    if isinstance(error, ConfigRevisionVersionConflictError):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="draft version does not match If-Match",
        )
    if isinstance(error, ActiveDraftExistsError):
        detail = "tenant already has an active draft"
    elif isinstance(error, ConfigRevisionImmutableError):
        detail = "published or archived revisions are immutable"
    else:
        detail = "config revision conflict"
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def prompt_http_exception(
    error: TenantNotFoundError | PromptRevisionError,
) -> HTTPException:
    if isinstance(error, TenantNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )
    detail = "prompt revision conflict"
    if error.__class__.__name__.endswith("NotFoundError"):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="prompt revision not found"
        )
    if error.__class__.__name__.endswith("VersionConflictError"):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="draft version does not match If-Match",
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def inbound_route_http_exception(
    error: (
        TenantNotFoundError | InboundRouteNotFoundError | InboundRouteDidConflictError
    ),
) -> HTTPException:
    if isinstance(error, TenantNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        )
    if isinstance(error, InboundRouteNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="inbound route not found",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="DID is already assigned to an inbound route",
    )


def etag(version: int) -> str:
    return f'"{version}"'


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match header is required",
        )
    if len(value) < 3 or value[0] != '"' or value[-1] != '"':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='If-Match must be a quoted positive integer, for example "7"',
        )
    raw_version = value[1:-1]
    if not raw_version.isdigit() or int(raw_version) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='If-Match must be a quoted positive integer, for example "7"',
        )
    return int(raw_version)


def text_response(revision: Any, *, key: str | None = None) -> dict[str, object]:
    data = {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "status": revision.status,
        "text": revision.text,
        "created_at": revision.created_at,
        "published_at": revision.published_at,
        "version": revision.version,
    }
    if key is not None:
        data["key"] = key
    return data


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: CreateTenantRequest,
    service: TenantServiceDependency,
) -> TenantResponse:
    try:
        tenant = await service.create(data)
    except TenantSlugConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tenant slug already exists",
        ) from error
    return TenantResponse.model_validate(tenant)


@router.get("/by-slug/{slug}", response_model=TenantResponse)
async def get_tenant_by_slug(
    slug: Slug,
    service: TenantServiceDependency,
) -> TenantResponse:
    try:
        tenant = await service.get_by_slug(slug)
    except TenantNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from error
    return TenantResponse.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    service: TenantServiceDependency,
) -> TenantResponse:
    try:
        tenant = await service.get(tenant_id)
    except TenantNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from error
    return TenantResponse.model_validate(tenant)


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    service: TenantServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[TenantResponse]:
    tenants = await service.list(offset=offset, limit=limit)
    return [TenantResponse.model_validate(tenant) for tenant in tenants]


@platform_router.post(
    "/system/drafts", response_model=PlatformPromptRevisionResponse, status_code=201
)
async def create_system_prompt_draft(
    data: CreatePlatformPromptDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
) -> dict[str, object]:
    try:
        revision = await use_cases.create_system_draft(data)
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return {
        **text_response(revision, key=data.key),
        "prompt_id": revision.system_prompt_id,
    }


@platform_router.patch(
    "/system/drafts/{revision_id}", response_model=PromptTextRevisionResponse
)
async def update_system_prompt_draft(
    revision_id: UUID,
    data: UpdateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    try:
        revision = await use_cases.update_system_draft(
            revision_id, data, parse_if_match(if_match)
        )
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return text_response(revision)


@platform_router.post(
    "/system/drafts/{revision_id}/publish", response_model=PromptTextRevisionResponse
)
async def publish_system_prompt_draft(
    revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> dict[str, object]:
    try:
        return text_response(await use_cases.publish_system(revision_id))
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error


@platform_router.get(
    "/system/{key}/revisions", response_model=list[PromptTextRevisionResponse]
)
async def list_system_prompt_revisions(
    key: str, use_cases: PromptCompositionUseCasesDependency
) -> list[dict[str, object]]:
    return [text_response(item) for item in await use_cases.list_system(key)]


@platform_router.post(
    "/profiles/drafts", response_model=PlatformPromptRevisionResponse, status_code=201
)
async def create_profile_prompt_draft(
    data: CreatePlatformPromptDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
) -> dict[str, object]:
    try:
        revision = await use_cases.create_profile_draft(data)
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return {
        **text_response(revision, key=data.key),
        "prompt_id": revision.profile_prompt_id,
    }


@platform_router.patch(
    "/profiles/drafts/{revision_id}", response_model=PromptTextRevisionResponse
)
async def update_profile_prompt_draft(
    revision_id: UUID,
    data: UpdateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    try:
        revision = await use_cases.update_profile_draft(
            revision_id, data, parse_if_match(if_match)
        )
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return text_response(revision)


@platform_router.post(
    "/profiles/drafts/{revision_id}/publish", response_model=PromptTextRevisionResponse
)
async def publish_profile_prompt_draft(
    revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> dict[str, object]:
    try:
        return text_response(await use_cases.publish_profile(revision_id))
    except PromptRevisionError as error:
        raise prompt_http_exception(error) from error


@platform_router.get(
    "/profiles/{key}/revisions", response_model=list[PromptTextRevisionResponse]
)
async def list_profile_prompt_revisions(
    key: str, use_cases: PromptCompositionUseCasesDependency
) -> list[dict[str, object]]:
    return [text_response(item) for item in await use_cases.list_profile(key)]


@platform_router.get("/profiles", response_model=list[str])
async def list_profiles(
    use_cases: PromptCompositionUseCasesDependency,
) -> list[str]:
    return [profile.key for profile in await use_cases.list_profiles()]


async def tenant_text_draft(
    tenant_id: UUID,
    data: CreateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    *,
    knowledge: bool,
) -> dict[str, object]:
    try:
        revision: Any = await (
            use_cases.create_knowledge_base_draft(tenant_id, data)
            if knowledge
            else use_cases.create_tenant_prompt_draft(tenant_id, data)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    if knowledge:
        return {
            **text_response(revision),
            "tenant_id": tenant_id,
            "knowledge_base_id": revision.knowledge_base_id,
        }
    return {
        **text_response(revision),
        "tenant_id": tenant_id,
        "prompt_id": revision.tenant_prompt_id,
    }


@router.post(
    "/{tenant_id}/tenant-prompt/drafts",
    response_model=TenantPromptRevisionResponse,
    status_code=201,
)
async def create_tenant_prompt_draft(
    tenant_id: UUID,
    data: CreateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
) -> dict[str, object]:
    return await tenant_text_draft(
        tenant_id, data, response, use_cases, knowledge=False
    )


@router.post(
    "/{tenant_id}/knowledge-base/drafts",
    response_model=KnowledgeBaseRevisionResponse,
    status_code=201,
)
async def create_knowledge_base_draft(
    tenant_id: UUID,
    data: CreateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
) -> dict[str, object]:
    return await tenant_text_draft(tenant_id, data, response, use_cases, knowledge=True)


@router.patch(
    "/{tenant_id}/tenant-prompt/drafts/{revision_id}",
    response_model=TenantPromptRevisionResponse,
)
async def update_tenant_prompt_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: UpdateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    try:
        revision = await use_cases.update_tenant_prompt_draft(
            tenant_id, revision_id, data, parse_if_match(if_match)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return {
        **text_response(revision),
        "tenant_id": tenant_id,
        "prompt_id": revision.tenant_prompt_id,
    }


@router.patch(
    "/{tenant_id}/knowledge-base/drafts/{revision_id}",
    response_model=KnowledgeBaseRevisionResponse,
)
async def update_knowledge_base_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: UpdateTextDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    try:
        revision = await use_cases.update_knowledge_base_draft(
            tenant_id, revision_id, data, parse_if_match(if_match)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return {
        **text_response(revision),
        "tenant_id": tenant_id,
        "knowledge_base_id": revision.knowledge_base_id,
    }


@router.post(
    "/{tenant_id}/tenant-prompt/drafts/{revision_id}/publish",
    response_model=TenantPromptRevisionResponse,
)
async def publish_tenant_prompt_draft(
    tenant_id: UUID, revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> dict[str, object]:
    try:
        revision = await use_cases.publish_tenant_prompt(tenant_id, revision_id)
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    return {
        **text_response(revision),
        "tenant_id": tenant_id,
        "prompt_id": revision.tenant_prompt_id,
    }


@router.post(
    "/{tenant_id}/knowledge-base/drafts/{revision_id}/publish",
    response_model=KnowledgeBaseRevisionResponse,
)
async def publish_knowledge_base_draft(
    tenant_id: UUID, revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> dict[str, object]:
    try:
        revision = await use_cases.publish_knowledge_base(tenant_id, revision_id)
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    return {
        **text_response(revision),
        "tenant_id": tenant_id,
        "knowledge_base_id": revision.knowledge_base_id,
    }


@router.get(
    "/{tenant_id}/tenant-prompt/revisions",
    response_model=list[TenantPromptRevisionResponse],
)
async def list_tenant_prompt_revisions(
    tenant_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> list[dict[str, object]]:
    return [
        {
            **text_response(item),
            "tenant_id": tenant_id,
            "prompt_id": item.tenant_prompt_id,
        }
        for item in await use_cases.list_tenant_prompts(tenant_id)
    ]


@router.get(
    "/{tenant_id}/knowledge-base/revisions",
    response_model=list[KnowledgeBaseRevisionResponse],
)
async def list_knowledge_base_revisions(
    tenant_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> list[dict[str, object]]:
    return [
        {
            **text_response(item),
            "tenant_id": tenant_id,
            "knowledge_base_id": item.knowledge_base_id,
        }
        for item in await use_cases.list_knowledge_bases(tenant_id)
    ]


@router.post(
    "/{tenant_id}/prompt-set/drafts",
    response_model=PromptSetRevisionResponse,
    status_code=201,
)
async def create_prompt_set_draft(
    tenant_id: UUID,
    data: CreatePromptSetDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
) -> PromptSetRevisionResponse:
    try:
        revision = await use_cases.create_prompt_set_draft(tenant_id, data)
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return PromptSetRevisionResponse.model_validate(revision)


@router.patch(
    "/{tenant_id}/prompt-set/drafts/{revision_id}",
    response_model=PromptSetRevisionResponse,
)
async def update_prompt_set_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: UpdatePromptSetDraftRequest,
    response: Response,
    use_cases: PromptCompositionUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PromptSetRevisionResponse:
    try:
        revision = await use_cases.update_prompt_set_draft(
            tenant_id, revision_id, data, parse_if_match(if_match)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return PromptSetRevisionResponse.model_validate(revision)


@router.post(
    "/{tenant_id}/prompt-set/drafts/{revision_id}/validate",
    response_model=ValidateDraftResponse,
)
async def validate_prompt_set_draft(
    tenant_id: UUID, revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> ValidateDraftResponse:
    try:
        errors = await use_cases.validate_prompt_set_draft(tenant_id, revision_id)
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error
    return ValidateDraftResponse(valid=not errors, errors=errors)


@router.post(
    "/{tenant_id}/prompt-set/drafts/{revision_id}/publish",
    response_model=PromptSetRevisionResponse,
)
async def publish_prompt_set_draft(
    tenant_id: UUID, revision_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> PromptSetRevisionResponse:
    try:
        return PromptSetRevisionResponse.model_validate(
            await use_cases.publish_prompt_set(tenant_id, revision_id)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error


@router.get(
    "/{tenant_id}/prompt-set/revisions", response_model=list[PromptSetRevisionResponse]
)
async def list_prompt_set_revisions(
    tenant_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> list[PromptSetRevisionResponse]:
    return [
        PromptSetRevisionResponse.model_validate(item)
        for item in await use_cases.list_prompt_sets(tenant_id)
    ]


@router.get("/{tenant_id}/prompt-set/active", response_model=PromptSetRevisionResponse)
async def active_prompt_set(
    tenant_id: UUID, use_cases: PromptCompositionUseCasesDependency
) -> PromptSetRevisionResponse:
    try:
        return PromptSetRevisionResponse.model_validate(
            await use_cases.active_prompt_set(tenant_id)
        )
    except (TenantNotFoundError, PromptRevisionError) as error:
        raise prompt_http_exception(error) from error


@router.post(
    "/{tenant_id}/inbound-routes",
    response_model=InboundRouteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inbound_route(
    tenant_id: UUID,
    data: CreateInboundRouteRequest,
    service: InboundRouteServiceDependency,
) -> InboundRouteResponse:
    try:
        route = await service.create(tenant_id, data)
    except (
        TenantNotFoundError,
        InboundRouteDidConflictError,
    ) as error:
        raise inbound_route_http_exception(error) from error
    return InboundRouteResponse.model_validate(route)


@router.get(
    "/{tenant_id}/inbound-routes",
    response_model=list[InboundRouteResponse],
)
async def list_inbound_routes(
    tenant_id: UUID,
    service: InboundRouteServiceDependency,
) -> list[InboundRouteResponse]:
    try:
        routes = await service.list(tenant_id)
    except TenantNotFoundError as error:
        raise inbound_route_http_exception(error) from error
    return [InboundRouteResponse.model_validate(route) for route in routes]


@router.patch(
    "/{tenant_id}/inbound-routes/{route_id}",
    response_model=InboundRouteResponse,
)
async def update_inbound_route(
    tenant_id: UUID,
    route_id: UUID,
    data: UpdateInboundRouteRequest,
    service: InboundRouteServiceDependency,
) -> InboundRouteResponse:
    try:
        route = await service.update(tenant_id, route_id, data)
    except (
        InboundRouteNotFoundError,
        InboundRouteDidConflictError,
    ) as error:
        raise inbound_route_http_exception(error) from error
    return InboundRouteResponse.model_validate(route)


@router.post(
    "/{tenant_id}/config/drafts",
    response_model=ConfigRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_config_draft(
    tenant_id: UUID,
    data: CreateDraftRequest,
    response: Response,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionResponse:
    try:
        revision = await use_cases.create_config_draft(tenant_id, data)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return ConfigRevisionResponse.model_validate(revision)


@router.get(
    "/{tenant_id}/config/drafts/{revision_id}",
    response_model=ConfigRevisionResponse,
)
async def get_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    response: Response,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionResponse:
    try:
        revision = await use_cases.get_config_draft(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return ConfigRevisionResponse.model_validate(revision)


@router.patch(
    "/{tenant_id}/config/drafts/{revision_id}",
    response_model=ConfigRevisionResponse,
)
async def update_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: UpdateDraftRequest,
    response: Response,
    use_cases: ConfigUseCasesDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ConfigRevisionResponse:
    try:
        revision = await use_cases.update_config_draft(
            tenant_id,
            revision_id,
            data,
            parse_if_match(if_match),
        )
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    response.headers["ETag"] = etag(revision.version)
    return ConfigRevisionResponse.model_validate(revision)


@router.post(
    "/{tenant_id}/config/drafts/{revision_id}/validate",
    response_model=ValidateDraftResponse,
)
async def validate_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ValidateDraftResponse:
    try:
        errors = await use_cases.validate_config_draft(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ValidateDraftResponse(valid=not errors, errors=errors)


@router.post(
    "/{tenant_id}/config/drafts/{revision_id}/publish",
    response_model=ConfigRevisionResponse,
)
async def publish_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionResponse:
    try:
        revision = await use_cases.publish_config_draft(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionResponse.model_validate(revision)


@router.post(
    "/{tenant_id}/config/import-yaml",
    response_model=LegacyConfigImportResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def import_legacy_yaml(
    tenant_id: UUID,
    raw_yaml: Annotated[
        str,
        Body(
            media_type="application/yaml",
            min_length=1,
            max_length=1_000_000,
        ),
    ],
    service: TenantServiceDependency,
    use_cases: ConfigUseCasesDependency,
    publish: Annotated[bool, Query()] = False,
) -> LegacyConfigImportResponse:
    try:
        document = parse_legacy_yaml(raw_yaml)
        tenant = await service.get(tenant_id)
        identity_errors = document.validate_tenant(tenant)
        if identity_errors:
            raise LegacyYamlError(identity_errors)

        revision = await use_cases.create_config_draft(
            tenant_id,
            CreateDraftRequest(
                config=document.config,
                comment="Imported from legacy YAML",
            ),
        )
        validation_errors = await use_cases.validate_config_draft(
            tenant_id,
            revision.id,
        )
        if publish and not validation_errors:
            revision = await use_cases.publish_config_draft(
                tenant_id,
                revision.id,
            )
    except LegacyYamlError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "invalid legacy YAML",
                "errors": [item.model_dump() for item in error.errors],
            },
        ) from error
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error

    return LegacyConfigImportResponse(
        revision=ConfigRevisionResponse.model_validate(revision),
        validation=ValidateDraftResponse(
            valid=not validation_errors,
            errors=validation_errors,
        ),
        source_tenant=document.identity,
        unsupported_fields=document.unsupported_fields,
    )


@router.get(
    "/{tenant_id}/config/revisions",
    response_model=list[ConfigRevisionResponse],
)
async def list_config_revisions(
    tenant_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> list[ConfigRevisionResponse]:
    try:
        revisions = await use_cases.list_config_revisions(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return [ConfigRevisionResponse.model_validate(revision) for revision in revisions]


@router.get(
    "/{tenant_id}/config/active",
    response_model=ActiveTenantConfig,
)
async def get_active_config(
    tenant_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ActiveTenantConfig:
    try:
        revision, config = await use_cases.get_active_config(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    assert revision.published_at is not None
    return ActiveTenantConfig(
        tenant_id=tenant_id,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        published_at=revision.published_at,
        config=config,
    )


@internal_router.get(
    "/tenants/{tenant_id}/active-config",
    response_model=ActiveTenantConfig,
    dependencies=[Depends(require_internal_scope("tenant-config:read"))],
)
async def get_internal_active_config(
    tenant_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ActiveTenantConfig:
    try:
        revision, config = await use_cases.get_internal_active_config(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    assert revision.published_at is not None
    return ActiveTenantConfig(
        tenant_id=tenant_id,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        published_at=revision.published_at,
        config=config,
    )


@internal_router.post(
    "/tenant-routing/resolve",
    response_model=TenantRouteResolutionResponse,
    dependencies=[Depends(require_internal_scope("tenant-routing:resolve"))],
)
async def resolve_tenant_route(
    data: ResolveTenantRouteRequest,
    service: InboundRouteServiceDependency,
) -> TenantRouteResolutionResponse:
    try:
        tenant, revision = await service.resolve(data.called_number)
    except InboundRouteUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="inbound route unavailable",
        ) from error
    return TenantRouteResolutionResponse(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        active_config_revision_id=revision.id,
        active_config_revision_number=revision.revision_number,
    )
