from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotCloneableError,
    ConfigRevisionNotFoundError,
    InvalidTenantConfigError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    ActiveConfigRead,
    ConfigRevisionClone,
    ConfigRevisionCreate,
    ConfigRevisionRead,
    ConfigRevisionUpdate,
    ConfigValidationResult,
    TenantCreate,
    TenantRead,
)
from backend_core.modules.tenants.service import (
    ConfigRevisionService,
    TenantService,
)
from backend_core.platform.database import DatabaseSession

router = APIRouter(prefix="/admin/v1/tenants", tags=["admin:tenants"])


def get_tenant_service(session: DatabaseSession) -> TenantService:
    return TenantService(TenantRepository(session))


TenantServiceDependency = Annotated[TenantService, Depends(get_tenant_service)]


def get_config_revision_service(
    session: DatabaseSession,
) -> ConfigRevisionService:
    return ConfigRevisionService(
        TenantRepository(session),
        ConfigRevisionRepository(session),
    )


ConfigRevisionServiceDependency = Annotated[
    ConfigRevisionService,
    Depends(get_config_revision_service),
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
    if isinstance(error, ActiveDraftExistsError):
        detail = "tenant already has an active draft"
    elif isinstance(error, ConfigRevisionImmutableError):
        detail = "published or archived revisions are immutable"
    elif isinstance(error, ConfigRevisionNotCloneableError):
        detail = "a draft revision cannot be cloned"
    else:
        detail = "config revision conflict"
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    service: TenantServiceDependency,
) -> TenantRead:
    try:
        tenant = await service.create(data)
    except TenantSlugConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tenant slug already exists",
        ) from error
    return TenantRead.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(
    tenant_id: UUID,
    service: TenantServiceDependency,
) -> TenantRead:
    try:
        tenant = await service.get(tenant_id)
    except TenantNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from error
    return TenantRead.model_validate(tenant)


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    service: TenantServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[TenantRead]:
    tenants = await service.list(offset=offset, limit=limit)
    return [TenantRead.model_validate(tenant) for tenant in tenants]


@router.post(
    "/{tenant_id}/config-revisions/drafts",
    response_model=ConfigRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_config_draft(
    tenant_id: UUID,
    data: ConfigRevisionCreate,
    service: ConfigRevisionServiceDependency,
) -> ConfigRevisionRead:
    try:
        revision = await service.create_draft(tenant_id, data)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.post(
    "/{tenant_id}/config-revisions/{revision_id}/clone",
    response_model=ConfigRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_config_revision(
    tenant_id: UUID,
    revision_id: UUID,
    data: ConfigRevisionClone,
    service: ConfigRevisionServiceDependency,
) -> ConfigRevisionRead:
    try:
        revision = await service.clone(tenant_id, revision_id, data)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.patch(
    "/{tenant_id}/config-revisions/{revision_id}",
    response_model=ConfigRevisionRead,
)
async def update_config_revision(
    tenant_id: UUID,
    revision_id: UUID,
    data: ConfigRevisionUpdate,
    service: ConfigRevisionServiceDependency,
) -> ConfigRevisionRead:
    try:
        revision = await service.update(tenant_id, revision_id, data)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.post(
    "/{tenant_id}/config-revisions/{revision_id}/validate",
    response_model=ConfigValidationResult,
)
async def validate_config_revision(
    tenant_id: UUID,
    revision_id: UUID,
    service: ConfigRevisionServiceDependency,
) -> ConfigValidationResult:
    try:
        await service.validate(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigValidationResult()


@router.post(
    "/{tenant_id}/config-revisions/{revision_id}/publish",
    response_model=ConfigRevisionRead,
)
async def publish_config_revision(
    tenant_id: UUID,
    revision_id: UUID,
    service: ConfigRevisionServiceDependency,
) -> ConfigRevisionRead:
    try:
        revision = await service.publish(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.get(
    "/{tenant_id}/config-revisions",
    response_model=list[ConfigRevisionRead],
)
async def list_config_revisions(
    tenant_id: UUID,
    service: ConfigRevisionServiceDependency,
) -> list[ConfigRevisionRead]:
    try:
        revisions = await service.list(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return [ConfigRevisionRead.model_validate(revision) for revision in revisions]


@router.get(
    "/{tenant_id}/config-revisions/active",
    response_model=ActiveConfigRead,
)
async def get_active_config(
    tenant_id: UUID,
    service: ConfigRevisionServiceDependency,
) -> ActiveConfigRead:
    try:
        revision, config = await service.get_active(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    assert revision.published_at is not None
    return ActiveConfigRead(
        tenant_id=tenant_id,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        published_at=revision.published_at,
        config=config,
    )
