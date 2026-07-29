from typing import Annotated
from uuid import UUID

from contracts import ActiveTenantConfig
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotFoundError,
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
    ConfigRevisionCreate,
    ConfigRevisionRead,
    ConfigRevisionUpdate,
    ConfigValidationResult,
    LegacyConfigImportResult,
    TenantCreate,
    TenantRead,
)
from backend_core.modules.tenants.service import (
    ConfigUseCases,
    TenantService,
)
from backend_core.platform.database import DatabaseSession

router = APIRouter(prefix="/admin/v1/tenants", tags=["admin:tenants"])
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
    if isinstance(error, ActiveDraftExistsError):
        detail = "tenant already has an active draft"
    elif isinstance(error, ConfigRevisionImmutableError):
        detail = "published or archived revisions are immutable"
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
    "/{tenant_id}/config/drafts",
    response_model=ConfigRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_config_draft(
    tenant_id: UUID,
    data: ConfigRevisionCreate,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionRead:
    try:
        revision = await use_cases.create_config_draft(tenant_id, data)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.patch(
    "/{tenant_id}/config/drafts/{revision_id}",
    response_model=ConfigRevisionRead,
)
async def update_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: ConfigRevisionUpdate,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionRead:
    try:
        revision = await use_cases.update_config_draft(
            tenant_id,
            revision_id,
            data,
        )
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.post(
    "/{tenant_id}/config/drafts/{revision_id}/validate",
    response_model=ConfigValidationResult,
)
async def validate_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ConfigValidationResult:
    try:
        errors = await use_cases.validate_config_draft(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigValidationResult(valid=not errors, errors=errors)


@router.post(
    "/{tenant_id}/config/drafts/{revision_id}/publish",
    response_model=ConfigRevisionRead,
)
async def publish_config_draft(
    tenant_id: UUID,
    revision_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> ConfigRevisionRead:
    try:
        revision = await use_cases.publish_config_draft(tenant_id, revision_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return ConfigRevisionRead.model_validate(revision)


@router.post(
    "/{tenant_id}/config/import-yaml",
    response_model=LegacyConfigImportResult,
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
    created_by: Annotated[UUID, Query()],
    service: TenantServiceDependency,
    use_cases: ConfigUseCasesDependency,
    publish: Annotated[bool, Query()] = False,
) -> LegacyConfigImportResult:
    try:
        document = parse_legacy_yaml(raw_yaml)
        tenant = await service.get(tenant_id)
        identity_errors = document.validate_tenant(tenant)
        if identity_errors:
            raise LegacyYamlError(identity_errors)

        revision = await use_cases.create_config_draft(
            tenant_id,
            ConfigRevisionCreate(
                config=document.config,
                created_by=created_by,
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

    return LegacyConfigImportResult(
        revision=ConfigRevisionRead.model_validate(revision),
        validation=ConfigValidationResult(
            valid=not validation_errors,
            errors=validation_errors,
        ),
        source_tenant=document.identity,
        unsupported_fields=document.unsupported_fields,
    )


@router.get(
    "/{tenant_id}/config/revisions",
    response_model=list[ConfigRevisionRead],
)
async def list_config_revisions(
    tenant_id: UUID,
    use_cases: ConfigUseCasesDependency,
) -> list[ConfigRevisionRead]:
    try:
        revisions = await use_cases.list_config_revisions(tenant_id)
    except (TenantNotFoundError, ConfigRevisionError) as error:
        raise config_http_exception(error) from error
    return [ConfigRevisionRead.model_validate(revision) for revision in revisions]


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
