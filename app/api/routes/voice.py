import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.routes.messages import (
    get_capability_router,
    get_conversation_repository,
    get_message_repository,
    get_tenant_config_loader,
    get_tool_call_repository,
)
from app.agent_runtime.voice_turn_processor import build_voice_message_service
from app.application.messages.process_incoming_message import (
    ConversationNotFoundError,
    ConversationTenantMismatchError,
)
from app.capabilities.router import CapabilityRouter
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.tenants.loader import (
    TenantConfigInvalidError,
    TenantConfigLoader,
    TenantConfigNotFoundError,
)
from app.voice.errors import VoiceServiceError
from app.voice.schemas import AudioInput, VoiceMessageRequest, VoiceMessageResponse
from app.voice.service import VoiceMessageService


router = APIRouter()


def get_voice_message_service(
    repository: MessageRepository = Depends(get_message_repository),
    tenant_config_loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
    tool_call_repository: ToolCallRepository = Depends(get_tool_call_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> VoiceMessageService:
    return build_voice_message_service(
        message_repository=repository,
        tenant_config_loader=tenant_config_loader,
        capability_router=capability_router,
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )


@router.post(
    "/messages",
    response_model=VoiceMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_voice_message(
    tenant_id: Annotated[str, Form()],
    channel: Annotated[str, Form()],
    audio_file: Annotated[UploadFile, File()],
    conversation_id: Annotated[str | None, Form()] = None,
    external_user_id: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
    service: VoiceMessageService = Depends(get_voice_message_service),
):
    try:
        voice_request = await build_voice_message_request_from_parts(
            tenant_id=tenant_id,
            channel=channel,
            audio_file=audio_file,
            conversation_id=conversation_id,
            external_user_id=external_user_id,
            metadata=metadata,
        )
        return service.process(voice_request)
    except TenantConfigNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant config not found")
    except TenantConfigInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ConversationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    except ConversationTenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except VoiceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message)


async def build_voice_message_request_from_parts(
    *,
    tenant_id: str,
    channel: str,
    audio_file: UploadFile,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
    metadata: str | None = None,
) -> VoiceMessageRequest:
    data = await audio_file.read()
    normalized_tenant_id = _required_text(tenant_id, "tenant_id")
    normalized_channel = _required_text(channel, "channel")

    return VoiceMessageRequest(
        tenant_id=normalized_tenant_id,
        conversation_id=_normalize_optional_text(conversation_id),
        channel=normalized_channel,
        external_user_id=_normalize_optional_text(external_user_id),
        audio=AudioInput(
            filename=audio_file.filename,
            content_type=audio_file.content_type,
            data=data,
            size_bytes=len(data),
        ),
        metadata=_parse_metadata(metadata),
    )


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} is required",
        )
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_metadata(raw_metadata: Any) -> dict[str, Any]:
    if raw_metadata is None:
        return {}
    raw_text = str(raw_metadata).strip()
    if not raw_text:
        return {}
    try:
        metadata = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="metadata must be valid JSON",
        ) from exc
    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="metadata must be a JSON object",
        )
    return metadata
