from typing import Annotated
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

from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotFoundError,
    ConfigRevisionVersionConflictError,
    InvalidTenantConfigError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.legacy_yaml import (
    LegacyYamlError,
    parse_legacy_yaml,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    ConfigRevisionResponse,
    CreateDraftRequest,
    CreateTenantRequest,
    LegacyConfigImportResponse,
    TenantResponse,
    UpdateDraftRequest,
    ValidateDraftResponse,
)
from backend_core.modules.tenants.service import (
    ConfigUseCases,
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
    prefix="/internal/v1/tenants",
    tags=["internal:tenants"],
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
    )


ConfigUseCasesDependency = Annotated[
    ConfigUseCases,
    Depends(get_config_use_cases),
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


def etag(version: int) -> str:
    return f'"{version}"'


def parse_if_match(value: str) -> int:
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
    if_match: Annotated[str, Header(alias="If-Match")],
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
    "/{tenant_id}/active-config",
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
