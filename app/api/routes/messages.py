import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from langchain_openai import AzureChatOpenAI

from app.application.messages.get_message import get_message_by_id_service
from app.application.capabilities.boundary import CapabilityExecutor, InProcessCapabilityExecutor
from app.application.capabilities.redis_executor import RedisCapabilityExecutor
from app.application.messages.process_incoming_message import (
    ConversationNotFoundError,
    ConversationTenantMismatchError,
    ProcessIncomingMessage,
)
from app.capabilities.router import CapabilityRouter
from app.core.config import CapabilitySettings
from app.infrastructure.database import get_db
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.schemas.tool_calls import ToolCallResponse
from app.agent.runtime import AgentRuntime
from app.tenants.loader import (
    TenantConfigInvalidError,
    TenantConfigLoader,
    TenantConfigNotFoundError,
)

router = APIRouter()

def get_message_repository(
    db: Session = Depends(get_db),
) -> MessageRepository:
    return MessageRepository(db)

def get_tool_call_repository(
    db: Session = Depends(get_db),
) -> ToolCallRepository:
    return ToolCallRepository(db)

def get_conversation_repository(
    db: Session = Depends(get_db),
) -> ConversationRepository:
    return ConversationRepository(db)

def get_agent_runtime() -> AgentRuntime:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not endpoint or not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be configured",
        )

    llm = AzureChatOpenAI(
        azure_endpoint=endpoint,
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        api_key=api_key,
        temperature=0,
    )

    return AgentRuntime(llm)

def get_tenant_config_loader() -> TenantConfigLoader:
    return TenantConfigLoader()

def get_capability_router() -> CapabilityRouter:
    return CapabilityRouter()

def get_capability_executor(
    tenant_config_loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
) -> CapabilityExecutor:
    settings = CapabilitySettings.from_env()
    if settings.execution_mode == "redis":
        return RedisCapabilityExecutor(settings=settings)
    return InProcessCapabilityExecutor(
        tenant_config_loader=tenant_config_loader,
        capability_router=capability_router,
    )

@router.post("", response_model=ProcessMessageResponse, status_code=status.HTTP_201_CREATED)
def receive_message(
    request: CreateMessageRequest,
    repository: MessageRepository = Depends(get_message_repository),
    agent_runtime: AgentRuntime = Depends(get_agent_runtime),
    tenant_config_loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
    capability_executor: CapabilityExecutor = Depends(get_capability_executor),
    tool_call_repository: ToolCallRepository = Depends(get_tool_call_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
):
    """
    Receive, store, and process a new message from a client/channel.
    """
    use_case = ProcessIncomingMessage(
        message_repository=repository,
        agent_runtime=agent_runtime,
        tenant_config_loader=tenant_config_loader,
        capability_router=capability_router,
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
        capability_executor=capability_executor,
    )
    try:
        response = use_case.execute(request)
    except TenantConfigNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant config not found")
    except TenantConfigInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ConversationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    except ConversationTenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

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

@router.get("/{message_id}/tool-calls", response_model=list[ToolCallResponse])
def list_message_tool_calls(
    message_id: str,
    repository: MessageRepository = Depends(get_message_repository),
    tool_call_repository: ToolCallRepository = Depends(get_tool_call_repository),
):
    """
    Retrieve capability executions associated with a message.
    """
    message = get_message_by_id_service(message_id, repository)

    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    return tool_call_repository.list_by_message_id(message_id)
