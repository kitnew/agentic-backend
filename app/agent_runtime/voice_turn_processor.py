from app.api.routes.messages import (
    get_agent_runtime,
    get_capability_executor,
    get_capability_router,
    get_tenant_config_loader,
)
from app.application.capabilities.boundary import CapabilityExecutor
from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.capabilities.router import CapabilityRouter
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.tenants.loader import TenantConfigLoader
from app.voice.schemas import VoiceMessageRequest, VoiceMessageResponse
from app.voice.service import VoiceMessageService


def build_voice_message_service(
    *,
    message_repository: MessageRepository,
    tenant_config_loader: TenantConfigLoader,
    capability_router: CapabilityRouter,
    tool_call_repository: ToolCallRepository,
    conversation_repository: ConversationRepository,
    capability_executor: CapabilityExecutor | None = None,
) -> VoiceMessageService:
    def build_message_processor() -> ProcessIncomingMessage:
        return ProcessIncomingMessage(
            message_repository=message_repository,
            agent_runtime=get_agent_runtime(),
            tenant_config_loader=tenant_config_loader,
            capability_router=capability_router,
            tool_call_repository=tool_call_repository,
            conversation_repository=conversation_repository,
            capability_executor=capability_executor,
        )

    return VoiceMessageService(
        tenant_config_loader=tenant_config_loader,
        message_processor_factory=build_message_processor,
    )


class VoiceTurnProcessor:
    def __init__(self, capability_executor: CapabilityExecutor | None = None):
        self.capability_executor = capability_executor

    def process(self, request: VoiceMessageRequest) -> VoiceMessageResponse:
        db = SessionLocal()
        try:
            tenant_config_loader = get_tenant_config_loader()
            capability_router = get_capability_router()
            service = build_voice_message_service(
                message_repository=MessageRepository(db),
                tenant_config_loader=tenant_config_loader,
                capability_router=capability_router,
                tool_call_repository=ToolCallRepository(db),
                conversation_repository=ConversationRepository(db),
                capability_executor=self.capability_executor or get_capability_executor(
                    tenant_config_loader, capability_router
                ),
            )
            return service.process(request)
        finally:
            db.close()
