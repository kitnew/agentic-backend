import logging
from contextlib import suppress
from hashlib import sha256
from typing import Annotated
from uuid import UUID, uuid4

from agentic_observability.domain import CoreMetrics
from contracts import (
    CallLifecycleResponse,
    CallLifecycleStatus,
    ConversationPersistenceStatus,
    HumanHandoffRequest,
    HumanHandoffResponse,
    InboundSipClaimRequest,
    InboundSipClaimResponse,
    LiveKitJobMetadata,
    VoiceAgentRuntimeContext,
    VoiceCallObservation,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from opentelemetry.trace import Tracer
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionLegacyRuntimeError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
    HumanHandoffError,
)
from backend_core.modules.calls.models import CallSession
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.schemas import (
    CallSessionResponse,
    CompleteCallSessionRequest,
    CreateCallSessionRequest,
    CreateTestVoiceSessionRequest,
    CreateTestVoiceSessionResponse,
    FailCallSessionRequest,
)
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.conversations.router import build_conversation_service
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptCompositionRepository,
    TenantRepository,
)
from backend_core.platform.auth import require_admin, require_internal_scope
from backend_core.platform.database import Database, DatabaseSession
from backend_core.platform.messaging import TransactionalOutboxBus
from backend_core.runtime.voice.repository import VoiceRuntimeRepository

router = APIRouter(prefix="/internal/v1/call-sessions", tags=["internal:calls"])
admin_router = APIRouter(
    prefix="/admin/v1/voice/test-sessions",
    tags=["admin:voice"],
    dependencies=[Depends(require_admin)],
)
runtime_router = APIRouter(prefix="/internal/v1/calls", tags=["internal:calls"])
call_admin_router = APIRouter(
    prefix="/admin/v1/calls",
    tags=["admin:calls"],
    dependencies=[Depends(require_admin)],
)

logger = logging.getLogger(__name__)


def build_call_session_service(
    session: AsyncSession,
    event_stream: str = "domain:events",
    command_stream: str = "application:commands",
    tracer: Tracer | None = None,
    metrics: CoreMetrics | None = None,
) -> CallSessionService:
    return CallSessionService(
        CallSessionRepository(session),
        InboundRouteRepository(session),
        PromptCompositionRepository(session),
        TenantRepository(session),
        ConfigRevisionRepository(session),
        VoiceRuntimeRepository(session),
        build_conversation_service(session),
        TransactionalOutboxBus(session, event_stream, command_stream, tracer),
        tracer,
        metrics,
    )


def get_call_session_service(
    session: DatabaseSession, request: Request
) -> CallSessionService:
    return build_call_session_service(
        session,
        request.app.state.settings.domain_event_stream,
        request.app.state.settings.command_stream,
        request.app.state.outbox_tracer,
        request.app.state.core_metrics,
    )


CallSessionServiceDependency = Annotated[
    CallSessionService,
    Depends(get_call_session_service),
]


def lifecycle_response(call: CallSession) -> CallLifecycleResponse:
    return CallLifecycleResponse(
        call_session_id=call.id,
        status=CallLifecycleStatus(call.status.value),
        started_at=call.started_at,
        connected_at=call.connected_at,
        ended_at=call.ended_at,
        failure_reason=call.failure_reason,
    )


@runtime_router.post(
    "/{call_id}/observations",
    response_model=CallLifecycleResponse,
    dependencies=[Depends(require_internal_scope("call-session:observe"))],
)
async def observe_call(
    call_id: UUID,
    data: VoiceCallObservation,
    service: CallSessionServiceDependency,
) -> CallLifecycleResponse:
    try:
        if data.observation_type == "session_started":
            call = await service.mark_started(call_id)
        elif data.observation_type == "participant_connected":
            call = await service.mark_connected(call_id)
        elif data.observation_type == "agent_relinquished":
            call = await service.relinquish_agent(
                call_id, ConversationPersistenceStatus(data.conversation_status)
            )
        elif data.observation_type == "session_finished":
            call = await service.end(
                call_id, ConversationPersistenceStatus(data.conversation_status)
            )
        else:
            assert data.failure_reason is not None
            call = await service.fail(
                call_id,
                data.failure_reason,
                ConversationPersistenceStatus(data.conversation_status),
            )
        return lifecycle_response(call)
    except (CallSessionNotFoundError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error


async def fail_test_call(
    database: Database, call_id: UUID, event_stream: str = "domain:events"
) -> None:
    with suppress(Exception):
        async with database.transaction() as session:
            await build_call_session_service(session, event_stream).fail(
                call_id,
                "livekit_setup_failed",
                ConversationPersistenceStatus.INCOMPLETE,
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
    if isinstance(error, CallSessionLegacyRuntimeError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "historical_call_voice_runtime_unavailable",
                "message": "this historical call has no pinned VoiceRuntime revision",
            },
        )
    if isinstance(error, CallSessionConfigUnavailableError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "tenant_configuration_not_voice_ready",
                "message": "tenant needs published config, PromptSet, and active VoiceRuntime revisions",
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


@runtime_router.post(
    "/inbound-sip/claim",
    response_model=InboundSipClaimResponse,
    dependencies=[Depends(require_internal_scope("call-session:inbound-sip:claim"))],
)
async def claim_inbound_sip_call(
    data: InboundSipClaimRequest,
    service: CallSessionServiceDependency,
) -> InboundSipClaimResponse:
    logger.info(
        "Inbound SIP claim requested",
        extra={
            "sip_call_id": data.sip_call_id,
            "room": data.room_name,
            "trunk_id": data.trunk_id,
        },
    )
    try:
        call, created = await service.claim_inbound_sip(data)
    except (
        CallSessionConfigUnavailableError,
        CallSessionConflictError,
        CallSessionRouteUnavailableError,
    ) as error:
        logger.warning(
            "Inbound SIP claim rejected",
            extra={
                "sip_call_id": data.sip_call_id,
                "room": data.room_name,
                "reason": type(error).__name__,
            },
        )
        raise call_http_exception(error) from error
    return InboundSipClaimResponse(call_session_id=call.id, created=created)


@runtime_router.post(
    "/{call_id}/handoff",
    response_model=HumanHandoffResponse,
    dependencies=[Depends(require_internal_scope("call-session:handoff"))],
)
async def transfer_call_to_human(
    call_id: UUID,
    data: HumanHandoffRequest,
    service: CallSessionServiceDependency,
    request: Request,
) -> HumanHandoffResponse:
    try:
        return await service.transfer_to_human(call_id, data, request.app.state.livekit)
    except HumanHandoffError as error:
        messages = {
            "handoff_not_configured": "Human handoff is not configured",
            "unknown_destination": "The requested handoff destination is unavailable",
            "call_not_transferable": "This call cannot be transferred",
            "transfer_failed": "The call could not be transferred",
        }
        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
                if error.code == "transfer_failed"
                else status.HTTP_409_CONFLICT
            ),
            detail={"code": error.code, "message": messages[error.code]},
        ) from error


@call_admin_router.get("/{call_id}", response_model=CallSessionResponse)
async def get_admin_call(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> CallSessionResponse:
    try:
        return CallSessionResponse.model_validate(await service.get(call_id))
    except CallSessionNotFoundError as error:
        raise call_http_exception(error) from error


@admin_router.post(
    "",
    response_model=CreateTestVoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_voice_session(
    data: CreateTestVoiceSessionRequest,
    request: Request,
    response: Response,
) -> CreateTestVoiceSessionResponse:
    database: Database = request.app.state.database
    raw_idempotency_key = request.headers.get("Idempotency-Key")
    idempotency_key = raw_idempotency_key.strip() if raw_idempotency_key else None
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid Idempotency-Key",
        )
    request_fingerprint = (
        sha256(f"admin-test-session:v1:{data.tenant_id}".encode()).hexdigest()
        if idempotency_key is not None
        else None
    )
    try:
        async with database.transaction() as session:
            call, created = await build_call_session_service(
                session,
                tracer=request.app.state.outbox_tracer,
                metrics=request.app.state.core_metrics,
            ).create_manual(
                data.tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
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
        if call.provider_dispatch_id is None:
            dispatch_id = await livekit.create_dispatch(
                agent_name=request.app.state.settings.livekit_agent_name,
                room_name=call.room_name,
                metadata=LiveKitJobMetadata(call_session_id=call.id).model_dump_json(),
            )
            try:
                async with database.transaction() as session:
                    call = await build_call_session_service(
                        session,
                        tracer=request.app.state.outbox_tracer,
                        metrics=request.app.state.core_metrics,
                    ).set_dispatch(
                        call.id,
                        dispatch_id,
                    )
            except CallSessionConflictError:
                with suppress(Exception):
                    await livekit.delete_dispatch(dispatch_id, call.room_name)
                async with database.transaction() as session:
                    call = await build_call_session_service(
                        session,
                        tracer=request.app.state.outbox_tracer,
                        metrics=request.app.state.core_metrics,
                    ).get(call.id)
        participant_identity = f"manual-test-{uuid4()}"
        participant_token = livekit.issue_participant_token(
            room_name=call.room_name,
            identity=participant_identity,
        )
    except Exception as error:
        if dispatch_id is not None:
            with suppress(Exception):
                await livekit.delete_dispatch(dispatch_id, call.room_name)
            with suppress(Exception):
                await livekit.delete_room(call.room_name)
        await fail_test_call(
            database, call.id, request.app.state.settings.domain_event_stream
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "livekit_setup_failed",
                "call_session_id": str(call.id),
            },
        ) from error

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
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
    dependencies=[Depends(require_internal_scope("call-session:runtime-context:read"))],
)
async def get_call_runtime_context(
    call_id: UUID,
    service: CallSessionServiceDependency,
) -> VoiceAgentRuntimeContext:
    try:
        return await service.get_runtime_context(call_id)
    except (
        CallSessionNotFoundError,
        CallSessionConfigUnavailableError,
        CallSessionLegacyRuntimeError,
    ) as error:
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
    data: CompleteCallSessionRequest | None = None,
) -> CallSessionResponse:
    try:
        return CallSessionResponse.model_validate(
            await service.complete(
                call_id,
                data.conversation_status
                if data is not None
                else ConversationPersistenceStatus.COMPLETE,
            )
        )
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
        call = await service.fail(
            call_id,
            data.failure_reason,
            data.conversation_status,
        )
    except (CallSessionNotFoundError, CallSessionConflictError) as error:
        raise call_http_exception(error) from error
    return CallSessionResponse.model_validate(call)
