from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.router import parse_if_match
from backend_core.modules.voice_runtime.errors import (
    RuntimeDraftExistsError,
    RuntimeNotFoundError,
    RuntimeRevisionImmutableError,
    RuntimeRevisionVersionConflictError,
    VoiceRuntimeError,
    VoiceRuntimeResolutionError,
)
from backend_core.modules.voice_runtime.repository import VoiceRuntimeRepository
from backend_core.modules.voice_runtime.schemas import (
    PlatformRuntimeRequest,
    PlatformRuntimeRevisionResponse,
    PlatformRuntimeStateResponse,
    RuntimeValidationResponse,
    TenantRuntimeRequest,
    TenantRuntimeRevisionResponse,
    TenantRuntimeStateResponse,
    VoiceRuntimeApplyResponse,
    VoiceRuntimePlanResponse,
    VoiceRuntimeRevisionResponse,
)
from backend_core.modules.voice_runtime.service import VoiceRuntimeUseCases
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

platform_router = APIRouter(
    prefix="/admin/v1/platform/runtime",
    tags=["admin:platform-runtime"],
    dependencies=[Depends(require_admin)],
)
tenant_router = APIRouter(
    prefix="/admin/v1/tenants",
    tags=["admin:tenant-runtime"],
    dependencies=[Depends(require_admin)],
)


def get_use_cases(session: DatabaseSession) -> VoiceRuntimeUseCases:
    return VoiceRuntimeUseCases(
        TenantRepository(session),
        ConfigRevisionRepository(session),
        VoiceRuntimeRepository(session),
    )


UseCases = Annotated[VoiceRuntimeUseCases, Depends(get_use_cases)]


def _raise(error: Exception) -> None:
    if isinstance(error, RuntimeNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime resource not found")
    if isinstance(error, RuntimeRevisionVersionConflictError):
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            "runtime draft changed; fetch current state and retry",
        )
    if isinstance(error, (RuntimeDraftExistsError, RuntimeRevisionImmutableError)):
        raise HTTPException(status.HTTP_409_CONFLICT, "runtime revision conflict")
    if isinstance(error, VoiceRuntimeResolutionError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": error.code, "path": error.path, "message": error.message},
        )
    raise error


@platform_router.get("", response_model=PlatformRuntimeStateResponse)
async def show_platform_runtime(use_cases: UseCases) -> PlatformRuntimeStateResponse:
    return await use_cases.platform_state()


@platform_router.get("/revisions", response_model=list[PlatformRuntimeRevisionResponse])
async def list_platform_runtime_revisions(
    use_cases: UseCases,
) -> list[PlatformRuntimeRevisionResponse]:
    return [
        PlatformRuntimeRevisionResponse.model_validate(item)
        for item in await use_cases.platform_revisions()
    ]


@platform_router.post("/validate", response_model=RuntimeValidationResponse)
async def validate_platform_runtime(
    data: PlatformRuntimeRequest,
) -> RuntimeValidationResponse:
    return RuntimeValidationResponse()


@platform_router.post(
    "/drafts",
    response_model=PlatformRuntimeRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_runtime_draft(
    data: PlatformRuntimeRequest, response: Response, use_cases: UseCases
) -> PlatformRuntimeRevisionResponse:
    try:
        revision = await use_cases.create_platform_draft(data.policy)
    except VoiceRuntimeError as error:
        _raise(error)
        raise
    response.headers["ETag"] = f'"{revision.version}"'
    return PlatformRuntimeRevisionResponse.model_validate(revision)


@platform_router.patch(
    "/drafts/{revision_id}", response_model=PlatformRuntimeRevisionResponse
)
async def update_platform_runtime_draft(
    revision_id: UUID,
    data: PlatformRuntimeRequest,
    response: Response,
    use_cases: UseCases,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PlatformRuntimeRevisionResponse:
    try:
        revision = await use_cases.update_platform_draft(
            revision_id, data.policy, parse_if_match(if_match)
        )
    except VoiceRuntimeError as error:
        _raise(error)
        raise
    response.headers["ETag"] = f'"{revision.version}"'
    return PlatformRuntimeRevisionResponse.model_validate(revision)


@platform_router.post(
    "/drafts/{revision_id}/publish",
    response_model=PlatformRuntimeRevisionResponse,
)
async def publish_platform_runtime_draft(
    revision_id: UUID, use_cases: UseCases
) -> PlatformRuntimeRevisionResponse:
    try:
        return PlatformRuntimeRevisionResponse.model_validate(
            await use_cases.publish_platform(revision_id)
        )
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.get("/{tenant_id}/runtime", response_model=TenantRuntimeStateResponse)
async def show_tenant_runtime(
    tenant_id: UUID, use_cases: UseCases
) -> TenantRuntimeStateResponse:
    try:
        return await use_cases.tenant_state(tenant_id)
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.get(
    "/{tenant_id}/runtime/revisions",
    response_model=list[TenantRuntimeRevisionResponse],
)
async def list_tenant_runtime_revisions(
    tenant_id: UUID, use_cases: UseCases
) -> list[TenantRuntimeRevisionResponse]:
    try:
        return [
            TenantRuntimeRevisionResponse.model_validate(item)
            for item in await use_cases.tenant_revisions(tenant_id)
        ]
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.post(
    "/{tenant_id}/runtime/validate", response_model=RuntimeValidationResponse
)
async def validate_tenant_runtime(
    tenant_id: UUID, data: TenantRuntimeRequest, use_cases: UseCases
) -> RuntimeValidationResponse:
    try:
        await use_cases.tenant_state(tenant_id)
        return RuntimeValidationResponse()
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.post(
    "/{tenant_id}/runtime/drafts",
    response_model=TenantRuntimeRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_runtime_draft(
    tenant_id: UUID,
    data: TenantRuntimeRequest,
    response: Response,
    use_cases: UseCases,
) -> TenantRuntimeRevisionResponse:
    try:
        revision = await use_cases.create_tenant_draft(tenant_id, data.settings)
    except VoiceRuntimeError as error:
        _raise(error)
        raise
    response.headers["ETag"] = f'"{revision.version}"'
    return TenantRuntimeRevisionResponse.model_validate(revision)


@tenant_router.patch(
    "/{tenant_id}/runtime/drafts/{revision_id}",
    response_model=TenantRuntimeRevisionResponse,
)
async def update_tenant_runtime_draft(
    tenant_id: UUID,
    revision_id: UUID,
    data: TenantRuntimeRequest,
    response: Response,
    use_cases: UseCases,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TenantRuntimeRevisionResponse:
    try:
        revision = await use_cases.update_tenant_draft(
            tenant_id, revision_id, data.settings, parse_if_match(if_match)
        )
    except VoiceRuntimeError as error:
        _raise(error)
        raise
    response.headers["ETag"] = f'"{revision.version}"'
    return TenantRuntimeRevisionResponse.model_validate(revision)


@tenant_router.post(
    "/{tenant_id}/runtime/drafts/{revision_id}/publish",
    response_model=TenantRuntimeRevisionResponse,
)
async def publish_tenant_runtime_draft(
    tenant_id: UUID, revision_id: UUID, use_cases: UseCases
) -> TenantRuntimeRevisionResponse:
    try:
        return TenantRuntimeRevisionResponse.model_validate(
            await use_cases.publish_tenant(tenant_id, revision_id)
        )
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.get(
    "/{tenant_id}/voice-runtime",
    response_model=VoiceRuntimeRevisionResponse,
)
async def show_voice_runtime(
    tenant_id: UUID, use_cases: UseCases
) -> VoiceRuntimeRevisionResponse:
    try:
        revision = await use_cases.active_voice_runtime(tenant_id)
        if revision is None:
            raise RuntimeNotFoundError
        return VoiceRuntimeRevisionResponse.model_validate(revision)
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.get(
    "/{tenant_id}/voice-runtime/revisions",
    response_model=list[VoiceRuntimeRevisionResponse],
)
async def list_voice_runtime_revisions(
    tenant_id: UUID, use_cases: UseCases
) -> list[VoiceRuntimeRevisionResponse]:
    try:
        return [
            VoiceRuntimeRevisionResponse.model_validate(item)
            for item in await use_cases.voice_revisions(tenant_id)
        ]
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.get(
    "/{tenant_id}/voice-runtime/plan", response_model=VoiceRuntimePlanResponse
)
async def plan_voice_runtime(
    tenant_id: UUID, use_cases: UseCases
) -> VoiceRuntimePlanResponse:
    try:
        return await use_cases.plan_voice_runtime(tenant_id)
    except VoiceRuntimeError as error:
        _raise(error)
        raise


@tenant_router.post(
    "/{tenant_id}/voice-runtime/apply", response_model=VoiceRuntimeApplyResponse
)
async def apply_voice_runtime(
    tenant_id: UUID, use_cases: UseCases
) -> VoiceRuntimeApplyResponse:
    try:
        return await use_cases.apply_voice_runtime(tenant_id)
    except VoiceRuntimeError as error:
        _raise(error)
        raise
