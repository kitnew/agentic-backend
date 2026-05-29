from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from langchain_openai import AzureChatOpenAI

from app.application.messages.get_message import get_message_by_id_service
from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.infrastructure.database import get_db
from app.infrastructure.repositories.message_repository import MessageRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.agent.runtime import AgentRuntime

router = APIRouter()

def get_message_repository(
    db: Session = Depends(get_db),
) -> MessageRepository:
    return MessageRepository(db)

def get_agent_runtime() -> AgentRuntime:
    # Use ChatOpenAI which will look for OPENAI_API_KEY from environment variables
    llm = AzureChatOpenAI(
        azure_endpoint="https://ct-val.cognitiveservices.azure.com/",
        azure_deployment="gpt-4o-mini",
        api_version="2025-01-01-preview",
        api_key="[ENCRYPTION_KEY]",
        temperature=0,
    )

    return AgentRuntime(llm)

@router.post("", response_model=ProcessMessageResponse, status_code=status.HTTP_201_CREATED)
def receive_message(
    request: CreateMessageRequest,
    repository: MessageRepository = Depends(get_message_repository),
    agent_runtime: AgentRuntime = Depends(get_agent_runtime),
):
    """
    Receive, store, and process a new message from a client/channel.
    """
    use_case = ProcessIncomingMessage(
        message_repository=repository,
        agent_runtime=agent_runtime,
    )
    response = use_case.execute(request)
    return response

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