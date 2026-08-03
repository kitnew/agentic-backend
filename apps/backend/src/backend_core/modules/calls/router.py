from contextlib import suppress
from typing import Annotated
from uuid import UUID, uuid4

from contracts import (
    CallLifecycleResponse,
    CallLifecycleStatus,
    LiveKitJobMetadata,
    VoiceAgentRuntimeContext,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
)
from backend_core.modules.calls.models import CallSession
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.schemas import (
    CallSessionResponse,
    CreateCallSessionRequest,
    CreateTestVoiceSessionRequest,
    CreateTestVoiceSessionResponse,
    FailCallSessionRequest,
)
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptBundleRevisionRepository,
    TenantRepository,
)
from backend_core.platform.auth import require_admin, require_internal_scope
from backend_core.platform.database import Database, DatabaseSession

router = APIRouter(prefix="/internal/v1/call-sessions", tags=["internal:calls"])
admin_router = APIRouter(
    prefix="/admin/v1/voice/test-sessions",
    tags=["admin:voice"],
    dependencies=[Depends(require_admin)],
)
runtime_router = APIRouter(prefix="/internal/v1/calls", tags=["internal:calls"])


def build_call_session_service(session: AsyncSession) -> CallSessionService:
    return CallSessionService(
        CallSessionRepository(session),
        InboundRouteRepository(session),
        PromptBundleRevisionRepository(session),
        TenantRepository(session),
        ConfigRevisionRepository(session),
    )


def get_call_session_service(session: DatabaseSession) -> CallSessionService:
    return build_call_session_service(session)


CallSessionServiceDependency = Annotated[
    CallSessionService,
    Depends(get_call_session_service),
]


def lifecycle_response(call: CallSession) -> CallLifecycleResponse:
    return CallLifecycleResponse(
        call_session_id=call.id,
        status=CallLifecycleStatus(call.status.value),
        started_at=call.started_at,
        ended_at=call.ended_at,
        failure_reason=call.failure_reason,
    )


async def fail_test_call(database: Database, call_id: UUID) -> None:
    with suppress(Exception):
        async with database.transaction() as session:
            await build_call_session_service(session).fail(
                call_id,
                "livekit_setup_failed",
            )


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


@admin_router.post(
    "",
    response_model=CreateTestVoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_voice_session(
    data: CreateTestVoiceSessionRequest,
    request: Request,
) -> CreateTestVoiceSessionResponse:
    database: Database = request.app.state.database
    try:
        async with database.transaction() as session:
            call = await build_call_session_service(session).create_manual(
                data.tenant_id
            )
    except TenantNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from error
    except (CallSessionConfigUnavailableError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error

    livekit = request.app.state.livekit
    dispatch_id: str | None = None
    try:
        dispatch_id = await livekit.create_dispatch(
            agent_name=request.app.state.settings.livekit_agent_name,
            room_name=call.room_name,
            metadata=LiveKitJobMetadata(
                call_session_id=call.id
            ).model_dump_json(),
        )
        async with database.transaction() as session:
            await build_call_session_service(session).set_dispatch(
                call.id,
                dispatch_id,
            )
        participant_identity = f"manual-test-{uuid4()}"
        participant_token = livekit.issue_participant_token(
            room_name=call.room_name,
            identity=participant_identity,
        )
    except Exception as error:
        if dispatch_id is not None:
            with suppress(Exception):
                await livekit.delete_dispatch(dispatch_id, call.room_name)
        await fail_test_call(database, call.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "livekit_setup_failed",
                "call_session_id": str(call.id),
            },
        ) from error

    return CreateTestVoiceSessionResponse(
        call_session_id=call.id,
        room_name=call.room_name,
        livekit_url=request.app.state.settings.livekit_public_url,
        participant_identity=participant_identity,
        participant_token=participant_token,
    )


@admin_router.get(
    "/{call_id}",
    response_model=CallLifecycleResponse,
)
async def get_test_voice_session(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> CallLifecycleResponse:
    try:
        return lifecycle_response(await service.get(call_id))
    except CallSessionNotFoundError as error:
        raise call_http_exception(error) from error


@runtime_router.get(
    "/{call_id}/runtime-context",
    response_model=VoiceAgentRuntimeContext,
    dependencies=[
        Depends(require_internal_scope("call-session:runtime-context:read"))
    ],
)
async def get_call_runtime_context(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> VoiceAgentRuntimeContext:
    try:
        return await service.get_runtime_context(call_id)
    except (CallSessionNotFoundError, CallSessionConfigUnavailableError) as error:
        raise call_http_exception(error) from error


@router.post(
    "/{call_id}/activate",
    response_model=CallSessionResponse,
    dependencies=[Depends(require_internal_scope("call-session:activate"))],
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
    dependencies=[Depends(require_internal_scope("call-session:complete"))],
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
    dependencies=[Depends(require_internal_scope("call-session:fail"))],
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
