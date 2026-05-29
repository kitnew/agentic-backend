import uuid
from datetime import datetime

from app.infrastructure.repositories.message_repository import MessageRepository
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentInput
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageStatus, MessageRole

class ProcessIncomingMessage:
    """
    Orchestration use-case class to handle incoming messages.
    """
    def __init__(self, message_repository: MessageRepository, agent_runtime: AgentRuntime):
        self.message_repository = message_repository
        self.agent_runtime = agent_runtime

    def execute(self, request: CreateMessageRequest) -> ProcessMessageResponse:
        # 1. Создать Message (role = user, status = received, intent = null)
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

        # 2. Сохранить Message
        self.message_repository.save(new_message)

        # 3. Обновить status = processing (and save)
        new_message.status = MessageStatus.PROCESSING
        self.message_repository.save(new_message)

        # 4. Создать AgentInput из Message + request
        agent_input = AgentInput(
            tenant_id=new_message.tenant_id,
            conversation_id=new_message.conversation_id,
            message_id=new_message.id,
            message_text=new_message.content,
            channel=new_message.channel,
            metadata=new_message.metadata,
        )

        try:
            # 5. Вызвать agent_runtime.run(agent_input)
            agent_result = self.agent_runtime.run(agent_input)

            # 6. Обновить Message (intent = agent_result.intent, status = processed, processed_at = now)
            new_message.intent = agent_result.intent
            new_message.status = MessageStatus.PROCESSED
            new_message.processed_at = datetime.now()

            # 7. Сохранить/обновить Message
            self.message_repository.save(new_message)

            # Format capabilities list to string representation
            requested_caps_str = None
            if agent_result.requested_capabilities:
                requested_caps_str = ", ".join(agent_result.requested_capabilities)

            # 8. Вернуть ProcessMessageResponse
            content_response = MessageResponse(
                id=new_message.id,
                tenant_id=new_message.tenant_id,
                conversation_id=new_message.conversation_id,
                channel=new_message.channel,
                external_user_id=new_message.external_user_id,
                role=new_message.role,
                content=new_message.content,
                intent=new_message.intent,
                status=new_message.status,
                metadata=new_message.metadata,
                created_at=new_message.created_at,
                processed_at=new_message.processed_at,
            )

            return ProcessMessageResponse(
                content=content_response,
                intent=new_message.intent,
                response_text=agent_result.response_text,
                requested_capabilities=requested_caps_str,
                status=new_message.status,
            )

        except Exception as e:
            # Если agent упал:
            # - status = failed
            # - processed_at = now
            # - сохранить ошибку в metadata или error field later
            # - вернуть ошибку или controlled response
            new_message.status = MessageStatus.FAILED
            new_message.processed_at = datetime.now()

            error_info = {"error": str(e)}
            if new_message.metadata:
                new_message.metadata = {**new_message.metadata, **error_info}
            else:
                new_message.metadata = error_info

            self.message_repository.save(new_message)

            content_response = MessageResponse(
                id=new_message.id,
                tenant_id=new_message.tenant_id,
                conversation_id=new_message.conversation_id,
                channel=new_message.channel,
                external_user_id=new_message.external_user_id,
                role=new_message.role,
                content=new_message.content,
                intent=new_message.intent,
                status=new_message.status,
                metadata=new_message.metadata,
                created_at=new_message.created_at,
                processed_at=new_message.processed_at,
            )

            return ProcessMessageResponse(
                content=content_response,
                intent=None,
                response_text="Failed to process the message due to an internal agent error.",
                requested_capabilities=None,
                status=new_message.status,
            )