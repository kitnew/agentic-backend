from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts import (
    AppendConversationMessage,
    ConversationPersistenceStatus,
)
from sqlalchemy.exc import IntegrityError

from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.conversations.errors import (
    ConversationConflictError,
    ConversationMessageConflictError,
    ConversationNotFoundError,
)
from backend_core.modules.conversations.models import Conversation, ConversationMessage
from backend_core.modules.conversations.repository import ConversationRepository


class ConversationService:
    def __init__(
        self,
        conversations: ConversationRepository,
        calls: CallSessionRepository,
    ) -> None:
        self._conversations = conversations
        self._calls = calls

    async def create_for_call(self, call_id: UUID, tenant_id: UUID) -> Conversation:
        existing = await self._conversations.get_for_call(call_id)
        if existing is not None:
            if existing.tenant_id != tenant_id:
                raise ConversationConflictError
            return existing
        conversation = Conversation(
            id=uuid4(),
            tenant_id=tenant_id,
            call_session_id=call_id,
        )
        try:
            return await self._conversations.add(conversation)
        except IntegrityError as error:
            existing = await self._conversations.get_for_call(call_id)
            if existing is None or existing.tenant_id != tenant_id:
                raise ConversationConflictError from error
            return existing

    async def append(
        self,
        call_id: UUID,
        data: AppendConversationMessage,
    ) -> tuple[ConversationMessage, bool]:
        call = await self._calls.get_for_update(call_id)
        if call is None:
            raise ConversationNotFoundError
        conversation = await self._conversations.get_for_call(
            call_id,
            for_update=True,
        )
        if conversation is None:
            raise ConversationNotFoundError
        if call.status.value in {"completed", "failed"}:
            raise ConversationConflictError
        if conversation.status is not ConversationPersistenceStatus.OPEN:
            raise ConversationConflictError

        existing = await self._conversations.get_message(data.message_id)
        if existing is not None:
            if (
                existing.tenant_id != conversation.tenant_id
                or existing.conversation_id != conversation.id
                or existing.role is not data.role
                or existing.content != data.content
                or existing.interrupted != data.interrupted
                or existing.source_created_at != data.source_created_at
            ):
                raise ConversationMessageConflictError
            return existing, False
        try:
            return await self._conversations.add_message(conversation, data), True
        except IntegrityError as error:
            existing = await self._conversations.get_message(data.message_id)
            if existing is None:
                raise ConversationMessageConflictError from error
            if (
                existing.conversation_id != conversation.id
                or existing.role is not data.role
                or existing.content != data.content
                or existing.interrupted != data.interrupted
                or existing.source_created_at != data.source_created_at
            ):
                raise ConversationMessageConflictError from error
            return existing, False

    async def close_for_call(
        self,
        call_id: UUID,
        status: ConversationPersistenceStatus,
    ) -> Conversation:
        conversation = await self._conversations.get_for_call(
            call_id,
            for_update=True,
        )
        if conversation is None:
            raise ConversationNotFoundError
        if conversation.status is ConversationPersistenceStatus.OPEN:
            conversation.status = status
            conversation.closed_at = datetime.now(UTC)
            conversation.updated_at = datetime.now(UTC)
            return conversation
        if conversation.status is not status:
            raise ConversationConflictError
        return conversation

    async def get_for_call(
        self,
        call_id: UUID,
    ) -> tuple[Conversation, list[ConversationMessage]]:
        conversation = await self._conversations.get_for_call(call_id)
        if conversation is None:
            raise ConversationNotFoundError
        return conversation, await self._conversations.list_messages(conversation.id)
