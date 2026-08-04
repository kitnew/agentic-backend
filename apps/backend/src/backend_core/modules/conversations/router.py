from typing import Annotated
from uuid import UUID

from contracts import (
    AppendConversationMessage,
    ConversationMessageResponse,
    ConversationResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.conversations.errors import (
    ConversationConflictError,
    ConversationMessageConflictError,
    ConversationNotFoundError,
)
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.modules.conversations.service import ConversationService
from backend_core.platform.auth import require_admin, require_internal_scope
from backend_core.platform.database import DatabaseSession

internal_router = APIRouter(prefix="/internal/v1/calls", tags=["internal:conversations"])
admin_router = APIRouter(
    prefix="/admin/v1/calls",
    tags=["admin:conversations"],
    dependencies=[Depends(require_admin)],
)


def build_conversation_service(session: AsyncSession) -> ConversationService:
    return ConversationService(
        ConversationRepository(session),
        CallSessionRepository(session),
    )


def get_conversation_service(session: DatabaseSession) -> ConversationService:
    return build_conversation_service(session)


ConversationServiceDependency = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]


def conversation_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, ConversationNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )
    if isinstance(error, ConversationMessageConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="conversation message conflict",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="conversation conflict",
    )


@internal_router.post(
    "/{call_session_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_scope("conversation-message:append"))],
)
async def append_conversation_message(
    call_session_id: UUID,
    data: AppendConversationMessage,
    service: ConversationServiceDependency,
    response: Response,
) -> ConversationMessageResponse:
    try:
        message, created = await service.append(call_session_id, data)
    except (
        ConversationConflictError,
        ConversationMessageConflictError,
        ConversationNotFoundError,
    ) as error:
        raise conversation_http_exception(error) from error
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ConversationMessageResponse(
        message_id=message.id,
        conversation_id=message.conversation_id,
        sequence_number=message.sequence_number,
        role=message.role,
        content=message.content,
        interrupted=message.interrupted,
        source_created_at=message.source_created_at,
        persisted_at=message.persisted_at,
    )


@admin_router.get(
    "/{call_session_id}/conversation",
    response_model=ConversationResponse,
)
async def get_admin_conversation(
    call_session_id: UUID,
    service: ConversationServiceDependency,
    response: Response,
) -> ConversationResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        conversation, messages = await service.get_for_call(call_session_id)
    except ConversationNotFoundError as error:
        raise conversation_http_exception(error) from error
    return ConversationResponse(
        conversation_id=conversation.id,
        call_session_id=conversation.call_session_id,
        status=conversation.status,
        created_at=conversation.created_at,
        closed_at=conversation.closed_at,
        messages=[
            ConversationMessageResponse(
                message_id=message.id,
                conversation_id=message.conversation_id,
                sequence_number=message.sequence_number,
                role=message.role,
                content=message.content,
                interrupted=message.interrupted,
                source_created_at=message.source_created_at,
                persisted_at=message.persisted_at,
            )
            for message in messages
        ],
    )
