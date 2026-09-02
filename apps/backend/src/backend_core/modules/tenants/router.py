from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend_core.modules.tenants.errors import (
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.release_repository import TenantReleaseRepository
from backend_core.modules.tenants.repository import (
    TelephonyRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    CreateTenantRequest,
    PlatformTelephonyResponse,
    Slug,
    TenantResponse,
    TenantTelephonyStatus,
)
from backend_core.modules.tenants.service import TenantService
from backend_core.modules.tenants.telephony import (
    PlatformTelephonyService,
    TenantTelephonyStatusService,
)
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants",
    tags=["admin:tenants"],
    dependencies=[Depends(require_admin)],
)
internal_router = APIRouter(prefix="/internal/v1", tags=["internal:tenants"])
platform_router = APIRouter(
    prefix="/admin/v1/platform/prompts",
    tags=["admin:platform-prompts"],
    dependencies=[Depends(require_admin)],
)
telephony_platform_router = APIRouter(
    prefix="/admin/v1/platform/telephony",
    tags=["admin:platform-telephony"],
    dependencies=[Depends(require_admin)],
)


def tenant_service(session: DatabaseSession) -> TenantService:
    return TenantService(TenantRepository(session), TenantReleaseRepository(session))


TenantServiceDependency = Annotated[TenantService, Depends(tenant_service)]


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: CreateTenantRequest, service: TenantServiceDependency
) -> TenantResponse:
    try:
        return TenantResponse.model_validate(await service.create(data))
    except TenantSlugConflictError as error:
        raise HTTPException(
            status_code=409, detail="tenant slug already exists"
        ) from error


@router.get("/by-slug/{slug}", response_model=TenantResponse)
async def get_tenant_by_slug(
    slug: Slug, service: TenantServiceDependency
) -> TenantResponse:
    try:
        return TenantResponse.model_validate(await service.get_by_slug(slug))
    except TenantNotFoundError as error:
        raise HTTPException(status_code=404, detail="tenant not found") from error


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID, service: TenantServiceDependency
) -> TenantResponse:
    try:
        return TenantResponse.model_validate(await service.get(tenant_id))
    except TenantNotFoundError as error:
        raise HTTPException(status_code=404, detail="tenant not found") from error


@router.get("/{tenant_id}/telephony/status", response_model=TenantTelephonyStatus)
async def tenant_telephony_status(
    tenant_id: UUID, session: DatabaseSession
) -> TenantTelephonyStatus:
    if await TenantRepository(session).get(tenant_id) is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return await TenantTelephonyStatusService(
        TelephonyRepository(session), TenantReleaseRepository(session)
    ).show(tenant_id)


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    service: TenantServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[TenantResponse]:
    return [
        TenantResponse.model_validate(item)
        for item in await service.list(offset=offset, limit=limit)
    ]


def platform_telephony_service(
    session: DatabaseSession, request: Request
) -> PlatformTelephonyService:
    return PlatformTelephonyService(
        TelephonyRepository(session),
        request.app.state.livekit,
        request.app.state.settings,
        request.app.state.control_plane,
        request.app.state.outbox_tracer,
        request.app.state.core_metrics,
    )


PlatformTelephonyServiceDependency = Annotated[
    PlatformTelephonyService, Depends(platform_telephony_service)
]


@telephony_platform_router.get("", response_model=PlatformTelephonyResponse)
async def show_platform_telephony(
    service: PlatformTelephonyServiceDependency,
) -> PlatformTelephonyResponse:
    return await service.show()


@telephony_platform_router.post("/reconcile", response_model=PlatformTelephonyResponse)
async def reconcile_platform_telephony(
    service: PlatformTelephonyServiceDependency,
) -> PlatformTelephonyResponse:
    return await service.reconcile()
