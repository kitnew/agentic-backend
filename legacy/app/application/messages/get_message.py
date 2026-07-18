import uuid
from datetime import datetime

from app.infrastructure.repositories.message_repository import MessageRepository
from app.schemas.messages import CreateMessageRequest
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageStatus, MessageRole

def get_message_by_id_service(
    message_id: str, 
    repository: MessageRepository,
) -> Message | None:
    message = repository.get_by_id(message_id)

    return message