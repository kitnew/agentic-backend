from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.application.messages.get_message import get_message_by_id_service
from app.infrastructure.database import get_db
from app.infrastructure.repositories.message_repository import MessageRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse
from app.application.messages.process_incoming_message import process_incoming_message_service

router = APIRouter()

def get_message_repository(
    db: Session = Depends(get_db),
) -> MessageRepository:
    return MessageRepository(db)

@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def receive_message(
    request: CreateMessageRequest,
    repository: MessageRepository = Depends(get_message_repository),
):
    """
    Receive and store a new message from a client/channel.
    """
    new_message = process_incoming_message_service(request, repository)
    return new_message

@router.get("/{message_id}", response_model=MessageResponse)
def get_message(
    message_id: str,
    repository: MessageRepository = Depends(get_message_repository),
):
    """
    Retrieve a specific message by its unique ID.
    """
    message = get_message_by_id_service(message_id, repository)
    
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        
    return message