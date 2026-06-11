from sqlalchemy.orm import Session

from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.infrastructure.models import ConversationModel


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, conversation: Conversation) -> Conversation:
        db_conversation = ConversationModel(
            id=conversation.id,
            tenant_id=conversation.tenant_id,
            channel=conversation.channel,
            external_user_id=conversation.external_user_id,
            status=conversation.status,
            extra_metadata=conversation.metadata,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        self.db.add(db_conversation)
        self.db.commit()
        return conversation

    def get_by_id(self, conversation_id: str) -> Conversation | None:
        db_conversation = (
            self.db.query(ConversationModel)
            .filter(ConversationModel.id == conversation_id)
            .first()
        )
        if not db_conversation:
            return None

        return self._to_domain(db_conversation)

    def get_active_by_participant(
        self,
        *,
        tenant_id: str,
        channel: str,
        external_user_id: str,
    ) -> Conversation | None:
        db_conversation = (
            self.db.query(ConversationModel)
            .filter(ConversationModel.tenant_id == tenant_id)
            .filter(ConversationModel.channel == channel)
            .filter(ConversationModel.external_user_id == external_user_id)
            .filter(ConversationModel.status == ConversationStatus.ACTIVE.value)
            .order_by(ConversationModel.updated_at.desc())
            .first()
        )
        if not db_conversation:
            return None

        return self._to_domain(db_conversation)

    def update(self, conversation: Conversation) -> Conversation:
        db_conversation = (
            self.db.query(ConversationModel)
            .filter(ConversationModel.id == conversation.id)
            .first()
        )
        if not db_conversation:
            return self.create(conversation)

        db_conversation.tenant_id = conversation.tenant_id
        db_conversation.channel = conversation.channel
        db_conversation.external_user_id = conversation.external_user_id
        db_conversation.status = conversation.status
        db_conversation.extra_metadata = conversation.metadata
        db_conversation.updated_at = conversation.updated_at
        self.db.commit()
        return conversation

    def _to_domain(self, db_conversation: ConversationModel) -> Conversation:
        return Conversation(
            id=db_conversation.id,
            tenant_id=db_conversation.tenant_id,
            channel=db_conversation.channel,
            external_user_id=db_conversation.external_user_id,
            status=db_conversation.status,
            metadata=db_conversation.extra_metadata,
            created_at=db_conversation.created_at,
            updated_at=db_conversation.updated_at,
        )
