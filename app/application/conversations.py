import uuid
from datetime import datetime

from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.infrastructure.repositories.conversation_repository import ConversationRepository


class ConversationNotFoundError(Exception):
    pass


class ConversationTenantMismatchError(Exception):
    pass


def resolve_conversation(
    repository: ConversationRepository,
    *,
    tenant_id: str,
    channel: str,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
) -> Conversation:
    if conversation_id:
        conversation = repository.get_by_id(conversation_id)
        if not conversation:
            raise ConversationNotFoundError(f"Conversation not found: {conversation_id}")
        if conversation.tenant_id != tenant_id:
            raise ConversationTenantMismatchError(
                f"Conversation {conversation_id} does not belong to tenant {tenant_id}"
            )
        conversation.updated_at = datetime.now()
        return repository.update(conversation)

    if external_user_id:
        conversation = repository.get_active_by_participant(
            tenant_id=tenant_id,
            channel=channel,
            external_user_id=external_user_id,
        )
        if conversation:
            conversation.updated_at = datetime.now()
            return repository.update(conversation)

    now = datetime.now()
    return repository.create(
        Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel=channel,
            external_user_id=external_user_id,
            status=ConversationStatus.ACTIVE,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
    )
