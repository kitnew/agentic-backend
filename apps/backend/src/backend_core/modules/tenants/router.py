from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend_core.modules.tenants.errors import (
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.modules.tenants.schemas import TenantCreate, TenantRead
from backend_core.modules.tenants.service import TenantService
from backend_core.platform.database import DatabaseSession

router = APIRouter(prefix="/admin/v1/tenants", tags=["admin:tenants"])


def get_tenant_service(session: DatabaseSession) -> TenantService:
    return TenantService(TenantRepository(session))


TenantServiceDependency = Annotated[TenantService, Depends(get_tenant_service)]


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
