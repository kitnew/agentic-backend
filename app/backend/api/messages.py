from fastapi import APIRouter

from app.backend.schemas.message import MessageRequest, MessageResponse
from app.backend.services.message_service import classify_message

messages_router = APIRouter()
        
@messages_router.post("/intent_classification")
def intent_classification(message: MessageRequest) -> MessageResponse:

    result = classify_message(message)
    
    return MessageResponse(
        content=result.content,
        intent=result.intent
    )