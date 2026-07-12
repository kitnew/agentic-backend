import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.routes.messages import get_tenant_config_loader
from app.core.config import AgentRuntimeSettings
from app.core.context import build_voice_runtime_context
from app.infrastructure.database import get_db
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader, TenantConfigNotFoundError
from app.voice.session_token import VoiceSessionClaims, VoiceSessionTokenCodec

router = APIRouter()


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
