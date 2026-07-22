import time
import json
from datetime import timedelta
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from livekit import api

from app.api.routes.messages import (
    get_capability_executor,
    get_capability_router,
    get_tenant_config_loader,
)
from app.agent.prompts.loader import PromptLoader
from app.application.capabilities.boundary import CapabilityExecutor
from app.application.capabilities.executor import BackendCapabilityExecutor
from app.application.messages.process_incoming_message import (
    ConversationNotFoundError,
    ConversationTenantMismatchError,
    resolve_conversation,
    ProcessIncomingMessage,
)
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest
from app.core.config import AgentRuntimeSettings
from app.core.context import build_voice_runtime_context
from app.infrastructure.database import get_db
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader, TenantConfigNotFoundError
from app.voice.session_token import VoiceSessionClaims, VoiceSessionTokenCodec
from app.voice.latency import (
    VoiceTurnConfig,
    VoiceTurnOverrides,
    resolve_voice_turn_config,
)
from app.voice_agent.models import SessionChatMessage
from app.voice_agent.session_factory import resolve_voice_id
from app.voice_agent.settings import LiveKitSettings

router = APIRouter()


def _authenticate_livekit_backend(authorization: str = Header(default="")) -> VoiceSessionClaims:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    try:
        settings = LiveKitSettings.from_env()
        return VoiceSessionTokenCodec(settings.session_token_secret).decode(
            authorization.removeprefix("Bearer ")
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid voice backend token") from exc


class CreateVoiceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    conversation_id: str | None = None
    mode: str = "manual"


class VoiceSessionResponse(BaseModel):
    call_session_id: str
    conversation_id: str | None = None
    websocket_url: str
    session_token: str
    expires_at: datetime
    mode: str


class CreateLiveKitSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    conversation_id: str | None = None
    turn_overrides: VoiceTurnOverrides | None = None


class LiveKitSessionResponse(BaseModel):
    runtime: str = "livekit"
    call_session_id: str
    conversation_id: str
    room_name: str
    livekit_url: str
    participant_token: str
    turn_config: VoiceTurnConfig


class PersistLiveKitMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str
    turn_id: str
    item_id: str
    interrupted: bool = False


class ExecuteLiveKitToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str
    arguments: dict
    turn_id: str
    tool_call_id: str


@router.post("/sessions", response_model=VoiceSessionResponse, response_model_exclude_none=True, status_code=status.HTTP_201_CREATED)
def create_voice_session(
    request: CreateVoiceSessionRequest,
    db: Session = Depends(get_db),
    loader: TenantConfigLoader = Depends(get_tenant_config_loader),
) -> VoiceSessionResponse:
    try:
        tenant = loader.load(request.tenant_id)
    except TenantConfigNotFoundError:
        raise HTTPException(status_code=404, detail="Tenant config not found")
    except TenantConfigInvalidError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not tenant.voice.enabled:
        raise HTTPException(status_code=403, detail="Voice mode is disabled")
    if request.conversation_id:
        conversation = ConversationRepository(db).get_by_id(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation.tenant_id != request.tenant_id:
            raise HTTPException(status_code=400, detail="Conversation does not belong to tenant")

    settings = AgentRuntimeSettings.from_env()
    if request.mode not in {"manual", "call"}:
        raise HTTPException(status_code=422, detail="mode must be 'manual' or 'call'")
    if request.mode == "call" and not settings.call_mode_enabled:
        raise HTTPException(status_code=403, detail="Voice call mode is disabled")
    now = int(time.time())
    call_session_id = str(uuid4())
    context = build_voice_runtime_context(tenant)
    claims = VoiceSessionClaims(
        tenant_id=request.tenant_id,
        call_session_id=call_session_id,
        conversation_id=request.conversation_id,
        language=context.language,
        timezone=context.timezone,
        iat=now,
        exp=now + (settings.call_session_ttl_seconds if request.mode == "call" else settings.session_token_ttl_seconds),
        mode=request.mode,
    )
    return VoiceSessionResponse(
        call_session_id=call_session_id,
        conversation_id=request.conversation_id,
        websocket_url=settings.public_ws_url,
        session_token=VoiceSessionTokenCodec(settings.session_token_secret).encode(claims),
        expires_at=datetime.fromtimestamp(claims.exp, timezone.utc),
        mode=request.mode,
    )


@router.post(
    "/livekit/sessions",
    response_model=LiveKitSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_livekit_session(
    request: CreateLiveKitSessionRequest,
    db: Session = Depends(get_db),
    loader: TenantConfigLoader = Depends(get_tenant_config_loader),
) -> LiveKitSessionResponse:
    settings = LiveKitSettings.from_env()
    if not settings.enabled:
        raise HTTPException(status_code=403, detail="LiveKit voice mode is disabled")
    try:
        settings.validate_api()
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
    context = ProcessIncomingMessage.build_agent_context_snapshot(
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
        SessionChatMessage(role=message.role.value, content=message.content)
        for message in MessageRepository(db).list_by_conversation_id(conversation.id)
        if message.role in {MessageRole.USER, MessageRole.ASSISTANT}
    )
    metadata = json.dumps(
        {
            "tenant_id": request.tenant_id,
            "call_session_id": call_session_id,
            "conversation_id": conversation.id,
            "channel": "voice",
            "language": tenant.default_language,
            "timezone": tenant.timezone,
            "instructions": PromptLoader().build_system_prompt(context),
            "greeting": tenant.agent.greeting_phrase,
            "enabled_capabilities": sorted(
                name for name, capability in tenant.capabilities.items() if capability.enabled
            ),
            "reservation_request_schema": (
                tenant.capabilities.get("reservation.create_request").config.get("row_format")
                if tenant.capabilities.get("reservation.create_request")
                else None
            ),
            "post_call_transcript": (
                tenant.post_call_transcript.model_dump(mode="json")
                if tenant.post_call_transcript
                else None
            ),
            "chat_history": [message.model_dump(mode="json") for message in history],
            "stt_language": tenant.voice.stt.language or tenant.default_language,
            "tts_voice_id": resolve_voice_id(tenant),
            "tts_model": tenant.voice.tts.model,
            "tts_language": tenant.voice.tts.language or tenant.default_language,
            "turn_config": turn_config.sanitized(),
        },
        separators=(",", ":"),
    )
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
    return LiveKitSessionResponse(
        call_session_id=call_session_id,
        conversation_id=conversation.id,
        room_name=room_name,
        livekit_url=settings.public_url,
        participant_token=token,
        turn_config=turn_config,
    )


@router.post("/livekit/messages")
def persist_livekit_message(
    request: PersistLiveKitMessageRequest,
    claims: VoiceSessionClaims = Depends(_authenticate_livekit_backend),
    db: Session = Depends(get_db),
):
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


@router.post("/livekit/tools")
async def execute_livekit_tool(
    request: ExecuteLiveKitToolRequest,
    claims: VoiceSessionClaims = Depends(_authenticate_livekit_backend),
    db: Session = Depends(get_db),
    loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
    capability_executor: CapabilityExecutor = Depends(get_capability_executor),
):
    tenant = loader.load(claims.tenant_id)
    capability = tenant.capabilities.get(request.capability)
    if not capability or not capability.enabled:
        raise HTTPException(status_code=403, detail="Capability is not enabled for tenant")
    message_id = _livekit_message_id(claims.call_session_id, "user", request.turn_id)
    message = MessageRepository(db).get_by_id(message_id)
    if message is None or message.tenant_id != claims.tenant_id:
        raise HTTPException(status_code=409, detail="User turn has not been persisted")
    arguments = dict(request.arguments)
    if request.capability == "reservation.create_request":
        arguments["raw_message"] = message.content
    execution = await BackendCapabilityExecutor(
        tenant_context=tenant,
        message=message,
        capability_router=capability_router,
        tool_call_repository=ToolCallRepository(db),
        capability_executor=capability_executor,
    ).execute_async(
        CapabilityRequest(
            name=request.capability,
            input=arguments,
            metadata={
                "call_session_id": claims.call_session_id,
                "turn_id": request.turn_id,
                "tool_call_id": request.tool_call_id,
                "idempotency_key": f"livekit:{claims.call_session_id}:{request.tool_call_id}",
            },
        )
    )
    return {
        "status": execution.result.status.value,
        "message": execution.result.user_message,
        "error": execution.result.error,
        "result": execution.result.output,
        "tool_call_id": execution.tool_call.id if execution.tool_call else None,
    }


def _livekit_message_id(call_session_id: str, role: str, item_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"livekit:{call_session_id}:{role}:{item_id}"))
