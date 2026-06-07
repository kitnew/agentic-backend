from sqlalchemy.orm import Session
from app.domain.messages.entities import Message
from app.infrastructure.models import MessageModel

class MessageRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, message: Message) -> Message:
        # Check if the message already exists in the database
        db_message = self.db.query(MessageModel).filter(MessageModel.id == message.id).first()
        
        if db_message:
            # Update existing record
            db_message.tenant_id = message.tenant_id
            db_message.conversation_id = message.conversation_id
            db_message.channel = message.channel
            db_message.external_user_id = message.external_user_id
            db_message.role = message.role
            db_message.content = message.content
            db_message.intent = message.intent
            db_message.status = message.status
            db_message.extra_metadata = message.metadata
            db_message.processed_at = message.processed_at
        else:
            # Insert new record
            db_message = MessageModel(
                id=message.id,
                tenant_id=message.tenant_id,
                conversation_id=message.conversation_id,
                channel=message.channel,
                external_user_id=message.external_user_id,
                role=message.role,
                content=message.content,
                intent=message.intent,
                status=message.status,
                extra_metadata=message.metadata,
                created_at=message.created_at,
                processed_at=message.processed_at,
            )
            self.db.add(db_message)
            
        self.db.commit()
        return message

    def get_by_id(self, message_id: str) -> Message | None:
        db_message = self.db.query(MessageModel).filter(MessageModel.id == message_id).first()
        if not db_message:
            return None
            
        return self._to_domain(db_message)

    def list_by_conversation_id(self, conversation_id: str) -> list[Message]:
        db_messages = (
            self.db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at.asc())
            .all()
        )
        return [self._to_domain(db_message) for db_message in db_messages]

    def _to_domain(self, db_message: MessageModel) -> Message:
        return Message(
            id=db_message.id,
            tenant_id=db_message.tenant_id,
            conversation_id=db_message.conversation_id,
            channel=db_message.channel,
            external_user_id=db_message.external_user_id,
            role=db_message.role,
            content=db_message.content,
            intent=db_message.intent,
            status=db_message.status,
            metadata=db_message.extra_metadata,
            created_at=db_message.created_at,
            processed_at=db_message.processed_at,
        )
