from datetime import UTC, datetime
from uuid import UUID

from contracts import AppendConversationMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.conversations.models import Conversation, ConversationMessage


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, conversation: Conversation) -> Conversation:
        async with self._session.begin_nested():
            self._session.add(conversation)
            await self._session.flush()
        return conversation

    async def get_for_call(
        self,
        call_id: UUID,
        *,
        for_update: bool = False,
    ) -> Conversation | None:
        query = select(Conversation).where(Conversation.call_session_id == call_id)
        if for_update:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def get_message(self, message_id: UUID) -> ConversationMessage | None:
        return await self._session.get(ConversationMessage, message_id)

    async def add_message(
        self,
        conversation: Conversation,
        data: AppendConversationMessage,
    ) -> ConversationMessage:
        message = ConversationMessage(
            id=data.message_id,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            sequence_number=conversation.next_sequence_number,
            role=data.role,
            content=data.content,
            interrupted=data.interrupted,
            source_created_at=data.source_created_at,
            persisted_at=datetime.now(UTC),
        )
        async with self._session.begin_nested():
            self._session.add(message)
            conversation.next_sequence_number += 1
            conversation.updated_at = datetime.now(UTC)
            await self._session.flush()
        return message

    async def list_messages(self, conversation_id: UUID) -> list[ConversationMessage]:
        return list(
            (
                await self._session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.sequence_number)
                )
            ).all()
        )
