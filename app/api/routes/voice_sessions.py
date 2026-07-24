import logging
from datetime import datetime, timedelta
from time import perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from livekit import api

from app.api.dependencies import (
    get_capability_executor,
    get_finalization_publisher,
    get_capability_router,
    get_tenant_config_loader,
)
from app.api.session_auth import authenticate_session_access
from app.agent.prompts.context import build_agent_context
from app.agent.prompts.loader import PromptLoader
from app.application.livekit_dispatch import resolve_runtime_tools, resolve_voice_id
from app.application.capabilities.boundary import CapabilityExecutor
from app.application.capabilities.redis_executor import RedisCapabilityExecutor
from app.application.capabilities.executor import BackendCapabilityExecutor
from app.application.conversations import (
    ConversationNotFoundError,
    ConversationTenantMismatchError,
    resolve_conversation,
)
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest
from app.contracts.livekit import (
    CreateLiveKitSessionRequest,
    ExecuteLiveKitToolResponse,
    ExecuteLiveKitToolRequest,
    LiveKitBackendClaims,
    LiveKitBackendTokenCodec,
    LiveKitJobMetadata,
    LiveKitSessionResponse,
    SessionChatMessage,
    SessionAccessClaims,
    FinalizeLiveKitCallRequest,
    FinalizeLiveKitCallResponse,
    PersistLiveKitMessageRequest,
    PersistLiveKitMessageResponse,
)
from app.core.config import LiveKitApiSettings, VoiceBackendAuthSettings
from app.application.call_sessions import (
    mark_finalization_enqueue_failed,
    mark_finalization_enqueued,
    prepare_finalization,
    require_active_call,
)
from app.domain.call_sessions.entities import CallSession as DurableCallSession
from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.infrastructure.database import get_db
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader, TenantConfigNotFoundError
from app.agent.schemas.voice import (
    resolve_voice_turn_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _authenticate_livekit_backend(authorization: str = Header(default="")) -> LiveKitBackendClaims:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    try:
        settings = VoiceBackendAuthSettings.from_env()
        return LiveKitBackendTokenCodec(settings.secret).decode(
            authorization.removeprefix("Bearer ")
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid voice backend token") from exc


@router.post(
    "/livekit/sessions",
    response_model=LiveKitSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_livekit_session(
    request: CreateLiveKitSessionRequest,
    db: Session = Depends(get_db),
    loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    caller: SessionAccessClaims = Depends(authenticate_session_access),
) -> LiveKitSessionResponse:
    if request.tenant_id not in caller.tenant_ids:
        if caller.subject == "staging-debug-chat":
            logger.warning(
                "Staging session issuance environment=staging tenant=%s outcome=forbidden",
                request.tenant_id,
            )
        raise HTTPException(status_code=403, detail="Tenant access is forbidden")
    settings = LiveKitApiSettings.from_env()
    if not settings.enabled:
        raise HTTPException(status_code=403, detail="LiveKit voice mode is disabled")
    try:
        settings.validate()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="LiveKit is not configured") from exc

    try:
        tenant = loader.load(request.tenant_id)
    except TenantConfigNotFoundError:
        raise HTTPException(status_code=404, detail="Tenant config not found")
    except TenantConfigInvalidError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not tenant.voice.enabled:
        raise HTTPException(status_code=403, detail="Voice mode is disabled")
    if request.turn_overrides is not None and not settings.turn_debug_overrides_enabled:
        raise HTTPException(status_code=403, detail="Voice turn debug configuration is disabled")

    turn_config = resolve_voice_turn_config(
        tenant.voice.turn,
        session_overrides=request.turn_overrides,
    )

    try:
        conversation = resolve_conversation(
            ConversationRepository(db),
            tenant_id=request.tenant_id,
            channel="voice",
            conversation_id=request.conversation_id,
        )
    except (ConversationNotFoundError, ConversationTenantMismatchError) as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    call_session_id = str(uuid4())
    room_name = f"voice-{call_session_id}"
    now = datetime.now()
    CallSessionRepository(db).create(
        DurableCallSession(
            id=call_session_id,
            tenant_id=request.tenant_id,
            conversation_id=conversation.id,
            livekit_room_name=room_name,
            status=CallSessionStatus.ACTIVE,
            finalization_status=CallFinalizationStatus.PENDING,
            started_at=now,
            updated_at=now,
        )
    )
    context = build_agent_context(
        tenant,
        conversation.id,
        metadata={
            "call_session_id": call_session_id,
            "channel": "voice",
            "language": tenant.default_language,
            "timezone": tenant.timezone,
            "thread_id": conversation.id,
        },
    )
    history = tuple(
        SessionChatMessage(
            role="user" if message.role == MessageRole.USER else "assistant",
            content=message.content,
        )
        for message in MessageRepository(db).list_by_conversation_id(conversation.id)
        if message.role in {MessageRole.USER, MessageRole.ASSISTANT}
    )
    metadata = LiveKitJobMetadata(
        tenant_id=request.tenant_id,
        call_session_id=call_session_id,
        conversation_id=conversation.id,
        channel="voice",
        language=tenant.default_language,
        timezone=tenant.timezone,
        instructions=PromptLoader().build_system_prompt(context),
        greeting=tenant.agent.greeting_phrase,
        tools=resolve_runtime_tools(tenant),
        end_call_enabled=tenant.voice.end_call_enabled,
        chat_history=history,
        stt_language=tenant.voice.stt.language or tenant.default_language,
        tts_voice_id=resolve_voice_id(tenant),
        tts_model=tenant.voice.tts.model,
        tts_language=tenant.voice.tts.language or tenant.default_language,
        turn_config=turn_config,
    ).model_dump_json()
    token = (
        api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(f"browser-{call_session_id}")
        .with_ttl(timedelta(seconds=settings.participant_token_ttl_seconds))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
                can_publish_sources=["microphone"],
                can_update_own_metadata=False,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=settings.agent_name, metadata=metadata)]
            )
        )
        .to_jwt()
    )
    response = LiveKitSessionResponse(
        call_session_id=call_session_id,
        conversation_id=conversation.id,
        room_name=room_name,
        livekit_url=settings.public_url,
        participant_token=token,
        turn_config=turn_config,
    )
    if caller.subject == "staging-debug-chat":
        logger.info(
            "Staging session issuance environment=staging tenant=%s outcome=issued",
            request.tenant_id,
        )
    return response


@router.post("/livekit/messages", response_model=PersistLiveKitMessageResponse)
def persist_livekit_message(
    request: PersistLiveKitMessageRequest,
    claims: LiveKitBackendClaims = Depends(_authenticate_livekit_backend),
    db: Session = Depends(get_db),
):
    require_active_call(CallSessionRepository(db), claims)
    message_id = _livekit_message_id(claims.call_session_id, request.role, request.item_id)
    now = datetime.now()
    message = Message(
        id=message_id,
        tenant_id=claims.tenant_id,
        conversation_id=claims.conversation_id,
        channel="voice",
        external_user_id=None,
        role=MessageRole(request.role),
        content=request.content,
        status=MessageStatus.PROCESSED,
        metadata={
            "call_session_id": claims.call_session_id,
            "turn_id": request.turn_id,
            "livekit_item_id": request.item_id,
            "interrupted": request.interrupted,
        },
        created_at=now,
        processed_at=now,
    )
    MessageRepository(db).save(message)
    return {"message_id": message_id, "status": message.status.value}


@router.post("/livekit/tools", response_model=ExecuteLiveKitToolResponse)
async def execute_livekit_tool(
    request: ExecuteLiveKitToolRequest,
    claims: LiveKitBackendClaims = Depends(_authenticate_livekit_backend),
    db: Session = Depends(get_db),
    loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
    capability_executor: CapabilityExecutor = Depends(get_capability_executor),
):
    require_active_call(CallSessionRepository(db), claims)
    repository = ToolCallRepository(db)
    existing = repository.get_by_livekit_identity(
        claims.tenant_id, claims.call_session_id, request.tool_call_id
    )
    if existing is not None:
        if (
            existing.capability_name != request.capability
            or existing.request_fingerprint != request.request_fingerprint
        ):
            raise HTTPException(status_code=409, detail="tool_call_id payload conflict")
        return ExecuteLiveKitToolResponse.model_validate(
            existing.response
            or {"status": existing.status.value, "tool_call_id": existing.id}
        )

    tenant = loader.load(claims.tenant_id)
    capability = tenant.capabilities.get(request.capability)
    if not capability or not capability.enabled:
        raise HTTPException(status_code=403, detail="Capability is not enabled for tenant")
    message_id = _livekit_message_id(claims.call_session_id, "user", request.turn_id)
    message = MessageRepository(db).get_by_id(message_id)
    if message is None or message.tenant_id != claims.tenant_id:
        raise HTTPException(status_code=409, detail="User turn has not been persisted")
    now = datetime.now()
    duplicate = repository.latest_livekit_capability(
        claims.tenant_id,
        claims.call_session_id,
        request.capability,
    )
    if duplicate and duplicate.input == request.arguments:
        if duplicate.status == ToolCallStatus.PENDING:
            return ExecuteLiveKitToolResponse(
                status="pending",
                message="Tool execution is already pending.",
                tool_call_id=duplicate.id,
            )
        cache_success = request.capability == "reservation.create_request" or (
            request.capability == "reservation.check_availability"
            and now - (duplicate.updated_at or duplicate.created_at)
            <= timedelta(
                seconds=tenant.reservation.flow.availability_result_ttl_seconds
            )
        )
        if (
            cache_success
            and duplicate.status == ToolCallStatus.SUCCESS
            and duplicate.response
        ):
            return ExecuteLiveKitToolResponse.model_validate(duplicate.response)
    durable_call, created = repository.reserve_livekit(
        ToolCall(
            id=str(uuid4()),
            tenant_id=claims.tenant_id,
            message_id=message.id,
            conversation_id=claims.conversation_id,
            call_session_id=claims.call_session_id,
            external_tool_call_id=request.tool_call_id,
            request_fingerprint=request.request_fingerprint,
            capability_name=request.capability,
            provider="pending",
            input=request.arguments,
            status=ToolCallStatus.PENDING,
            latency_ms=0,
            created_at=now,
            updated_at=now,
        )
    )
    if (
        durable_call.capability_name != request.capability
        or durable_call.request_fingerprint != request.request_fingerprint
    ):
        raise HTTPException(status_code=409, detail="tool_call_id payload conflict")
    if not created:
        return ExecuteLiveKitToolResponse.model_validate(
            durable_call.response
            or {"status": durable_call.status.value, "tool_call_id": durable_call.id}
        )

    arguments = dict(request.arguments)
    if (
        request.capability == "reservation.create_request"
        and tenant.reservation.flow.availability_before_guest_details
    ):
        availability = repository.latest_livekit_capability(
            claims.tenant_id,
            claims.call_session_id,
            "reservation.check_availability",
        )
        availability_error = _matching_availability_error(
            availability,
            arguments,
            now=now,
            ttl_seconds=tenant.reservation.flow.availability_result_ttl_seconds,
        )
        if availability_error:
            response = ExecuteLiveKitToolResponse(
                status="skipped",
                message="Pred rezerváciou treba znova úspešne overiť dostupnosť.",
                error=availability_error,
                tool_call_id=durable_call.id,
            )
            repository.complete_livekit(
                durable_call.id,
                status=ToolCallStatus.SKIPPED,
                provider="validation",
                output=None,
                error=availability_error,
                response=response.model_dump(mode="json"),
                latency_ms=0,
                updated_at=datetime.now(),
            )
            return response
        availability_output = availability.output or {}
        arguments["requested_room_type"] = arguments["room_type"]
        arguments["room_type"] = availability_output["allocated_room_type"]
    if request.capability == "reservation.create_request":
        arguments["raw_message"] = message.content
    started_at = perf_counter()
    try:
        execution = await BackendCapabilityExecutor(
            tenant_context=tenant,
            message=message,
            capability_router=capability_router,
            tool_call_repository=repository,
            capability_executor=capability_executor,
            persist_tool_call=False,
        ).execute_async(
            CapabilityRequest(
                name=request.capability,
                input=arguments,
                metadata={
                    "call_session_id": claims.call_session_id,
                    "turn_id": request.turn_id,
                    "tool_call_id": request.tool_call_id,
                    "durable_tool_call_id": durable_call.id,
                    "idempotency_key": (
                        f"livekit:{claims.call_session_id}:{request.tool_call_id}"
                    ),
                },
            )
        )
        if (
            execution.execution_result
            and execution.execution_result.error_code == "capability_result_timeout"
        ):
            return ExecuteLiveKitToolResponse(
                status="pending",
                message="Tool execution is still pending.",
                tool_call_id=durable_call.id,
            )
        response = ExecuteLiveKitToolResponse(
            status=execution.result.status.value,
            message=execution.result.user_message,
            error=execution.result.error,
            result=execution.result.output,
            tool_call_id=durable_call.id,
        )
        repository.complete_livekit(
            durable_call.id,
            status=ToolCallStatus(execution.result.status.value),
            provider=execution.result.provider,
            output=execution.result.output,
            error=execution.result.error,
            response=response.model_dump(mode="json"),
            latency_ms=int((perf_counter() - started_at) * 1000),
            updated_at=datetime.now(),
        )
        return response
    except Exception as exc:
        error = str(exc)[:8_192]
        response = ExecuteLiveKitToolResponse(
            status="failed", error=error, tool_call_id=durable_call.id
        )
        repository.complete_livekit(
            durable_call.id,
            status=ToolCallStatus.FAILED,
            provider="backend",
            output=None,
            error=error,
            response=response.model_dump(mode="json"),
            latency_ms=int((perf_counter() - started_at) * 1000),
            updated_at=datetime.now(),
        )
        return response


@router.post("/livekit/finalize", response_model=FinalizeLiveKitCallResponse)
async def finalize_livekit_call(
    request: FinalizeLiveKitCallRequest,
    claims: LiveKitBackendClaims = Depends(_authenticate_livekit_backend),
    db: Session = Depends(get_db),
    finalization_publisher: RedisCapabilityExecutor = Depends(get_finalization_publisher),
):
    repository = CallSessionRepository(db)
    call, command = prepare_finalization(repository, claims, request)
    queued = False
    if command is not None:
        try:
            await finalization_publisher.enqueue(command)
            call = mark_finalization_enqueued(repository, call.id, command.command_id)
            queued = True
        except Exception as exc:
            mark_finalization_enqueue_failed(repository, call.id, command.command_id, str(exc))
            raise HTTPException(status_code=503, detail="Finalization could not be queued") from exc
    if call.status == CallSessionStatus.ACTIVE:
        raise RuntimeError("finalization did not make the call terminal")
    return FinalizeLiveKitCallResponse(
        call_session_id=call.id,
        call_status=call.status.value,
        finalization_status=call.finalization_status.value,
        queued=queued,
        transcript_sheet_range=call.transcript_sheet_range,
        error=call.finalization_error,
    )


def _livekit_message_id(call_session_id: str, role: str, item_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"livekit:{call_session_id}:{role}:{item_id}"))


def _matching_availability_error(
    availability: ToolCall | None,
    arguments: dict,
    *,
    now: datetime,
    ttl_seconds: int,
) -> str | None:
    if availability is None:
        return "availability_check_required"
    if availability.status != ToolCallStatus.SUCCESS:
        return "availability_check_invalid"
    checked_at = availability.updated_at or availability.created_at
    if now - checked_at > timedelta(seconds=ttl_seconds):
        return "availability_check_expired"
    output = availability.output or {}
    expected = {
        "check_in": arguments.get("check_in"),
        "check_out": arguments.get("check_out"),
        "room_type": arguments.get("room_type"),
        "room_count": arguments.get("room_count"),
    }
    actual = {
        key: availability.input.get(key)
        for key in ("check_in", "check_out", "room_type", "room_count")
    }
    if actual != expected:
        return "availability_check_required"
    if (
        output.get("status") != "available"
        or output.get("requested_room_type") != expected["room_type"]
        or output.get("check_in") != expected["check_in"]
        or output.get("check_out") != expected["check_out"]
        or output.get("requested_rooms") != expected["room_count"]
        or not output.get("allocated_room_type")
    ):
        return "availability_check_invalid"
    return None
