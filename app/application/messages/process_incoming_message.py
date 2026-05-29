import uuid
from datetime import datetime

from app.infrastructure.repositories.message_repository import MessageRepository
from app.schemas.messages import CreateMessageRequest
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageStatus, MessageRole

def process_incoming_message_service(
    request: CreateMessageRequest, 
    repository: MessageRepository,
) -> Message:
    new_message = Message(
        id=str(uuid.uuid4()),
        tenant_id=request.tenant_id,
        channel=request.channel,
        external_user_id=request.external_user_id,
        conversation_id=request.conversation_id,
        role=MessageRole.USER,
        content=request.content,
        intent=None,
        status=MessageStatus.RECEIVED,
        metadata=request.metadata,
        created_at=datetime.now(),
        processed_at=None,
    )

    repository.save(new_message)

    return new_message