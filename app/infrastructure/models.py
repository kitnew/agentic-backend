from sqlalchemy import Column, String, DateTime, JSON
from app.infrastructure.database import Base

class MessageModel(Base):
    """
    SQLAlchemy model representing the 'messages' table.
    """
    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    channel = Column(String, nullable=False)
    external_user_id = Column(String, nullable=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    intent = Column(String, nullable=True)
    status = Column(String, nullable=False)
    
    # We map the database column "metadata" to "extra_metadata" to avoid conflict
    # with the SQLAlchemy Base's reserved property 'metadata'
    extra_metadata = Column("metadata", JSON, nullable=True)
    
    created_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, nullable=True)
