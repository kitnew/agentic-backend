from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
)
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.schemas import (
    CallSessionResponse,
    CreateCallSessionRequest,
    FailCallSessionRequest,
)
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.tenants.repository import (
    InboundRouteRepository,
    PromptBundleRevisionRepository,
)
from backend_core.platform.auth import require_internal_scope
from backend_core.platform.database import DatabaseSession

router = APIRouter(prefix="/internal/v1/call-sessions", tags=["internal:calls"])


def get_call_session_service(session: DatabaseSession) -> CallSessionService:
    return CallSessionService(
        CallSessionRepository(session),
        InboundRouteRepository(session),
        PromptBundleRevisionRepository(session),
    )


CallSessionServiceDependency = Annotated[
    CallSessionService,
    Depends(get_call_session_service),
]


def call_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, CallSessionNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="call session not found",
        )
    if isinstance(error, CallSessionRouteUnavailableError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="inbound route unavailable",
        )
    if isinstance(error, CallSessionConfigUnavailableError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "tenant_configuration_not_voice_ready",
                "message": "tenant active configuration must be schema version 2 with a published prompt bundle",
            },
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="call session conflict",
    )


@router.post(
    "",
    response_model=CallSessionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_scope("call-session:create"))],
)
async def create_call_session(
    data: CreateCallSessionRequest,
    service: CallSessionServiceDependency,
    response: Response,
) -> CallSessionResponse:
    try:
        call, created = await service.create(data)
    except (
        CallSessionConfigUnavailableError,
        CallSessionConflictError,
        CallSessionRouteUnavailableError,
    ) as error:
        raise call_http_exception(error) from error
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return CallSessionResponse.model_validate(call)


@router.post(
    "/{call_id}/activate",
    response_model=CallSessionResponse,
    dependencies=[Depends(require_internal_scope("call-session:write"))],
)
async def activate_call_session(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> CallSessionResponse:
    try:
        return CallSessionResponse.model_validate(await service.activate(call_id))
    except (CallSessionNotFoundError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error


@router.post(
    "/{call_id}/complete",
    response_model=CallSessionResponse,
    dependencies=[Depends(require_internal_scope("call-session:write"))],
)
async def complete_call_session(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> CallSessionResponse:
    try:
        return CallSessionResponse.model_validate(await service.complete(call_id))
    except (CallSessionNotFoundError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error


@router.post(
    "/{call_id}/fail",
    response_model=CallSessionResponse,
    dependencies=[Depends(require_internal_scope("call-session:write"))],
)
async def fail_call_session(
    call_id: UUID,
    data: FailCallSessionRequest,
    service: CallSessionServiceDependency,
) -> CallSessionResponse:
    try:
        call = await service.fail(call_id, data.failure_reason)
    except (CallSessionNotFoundError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error
    return CallSessionResponse.model_validate(call)
