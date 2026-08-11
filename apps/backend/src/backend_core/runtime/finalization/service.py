from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts import (
    CallEventPayload,
    CommandResult,
    ExecutePostCallAction,
    GenerateCallSummary,
    ManagedWebhookCapability,
    ManagedWebhookPostJsonPlan,
    MessageEnvelope,
    TenantConfigV3,
    command_envelope,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.application.messaging import CommandBus
from backend_core.modules.calls.models import CallSession
from backend_core.modules.conversations.models import Conversation, ConversationMessage
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationProvider,
)
from backend_core.modules.tenants.models import TenantConfigRevision
from backend_core.runtime.capabilities.domain import JsonataMappingEngine
from backend_core.runtime.finalization.models import (
    CallFinalization,
    FinalizationStatus,
)


class FinalizationError(ValueError):
    pass


class FinalizationService:
    def __init__(self, session: AsyncSession, commands: CommandBus) -> None:
        self._session = session
        self._commands = commands

    async def start(self, event: MessageEnvelope) -> CallFinalization:
        if event.message_kind != "event" or event.message_type != "call.ended":
            raise FinalizationError("finalization requires call.ended")
        payload = CallEventPayload.model_validate(event.payload)
        if payload.status != "ended":
            raise FinalizationError("call.ended payload is invalid")
        existing = await self._session.scalar(
            select(CallFinalization)
            .where(CallFinalization.call_id == payload.call_id)
            .with_for_update()
        )
        if existing is not None:
            return existing
        call = await self._session.get(CallSession, payload.call_id)
        if call is None or call.status.value != "ended":
            raise FinalizationError("ended call not found")
        config = await self._config(call)
        finalization = CallFinalization(
            id=uuid4(),
            call_id=call.id,
            tenant_id=call.tenant_id,
            status=FinalizationStatus.PROCESSING,
            action_ids=[action.action_id for action in config.post_call_actions],
            next_action_index=0,
        )
        self._session.add(finalization)
        await self._session.flush()
        command = command_envelope(
            GenerateCallSummary(call_id=call.id, finalization_id=finalization.id),
            tenant_id=call.tenant_id,
            correlation_id=call.id,
            causation_id=event.message_id,
        )
        finalization.current_command_id = command.message_id
        await self._commands.send(command)
        return finalization

    async def handle_result(
        self, envelope: MessageEnvelope, result: CommandResult
    ) -> CallFinalization | None:
        finalization = await self._session.scalar(
            select(CallFinalization)
            .where(CallFinalization.current_command_id == result.command_id)
            .with_for_update()
        )
        if finalization is None or finalization.status is not FinalizationStatus.PROCESSING:
            return finalization
        expected_type = (
            "call.generate_summary.v1"
            if finalization.summary is None
            else "call.execute_post_call_action.v1"
        )
        if result.command_type != expected_type:
            raise FinalizationError("command result does not match current step")
        if result.status == "failed":
            assert result.error is not None
            finalization.status = FinalizationStatus.FAILED
            finalization.last_error = f"{result.error.code}: {result.error.message}"[:1000]
            finalization.completed_at = datetime.now(UTC)
            return finalization
        if result.command_type == "call.generate_summary.v1":
            assert result.output is not None
            summary = result.output.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise FinalizationError("summary result is invalid")
            finalization.summary = summary.strip()
        else:
            finalization.next_action_index += 1
        if finalization.next_action_index >= len(finalization.action_ids):
            finalization.status = FinalizationStatus.COMPLETED
            finalization.completed_at = datetime.now(UTC)
            finalization.current_command_id = None
            return finalization
        action_id = finalization.action_ids[finalization.next_action_index]
        command = command_envelope(
            ExecutePostCallAction(
                call_id=finalization.call_id,
                finalization_id=finalization.id,
                action_id=action_id,
            ),
            tenant_id=finalization.tenant_id,
            correlation_id=finalization.call_id,
            causation_id=envelope.message_id,
        )
        finalization.current_command_id = command.message_id
        await self._commands.send(command)
        return finalization

    async def summary_context(
        self, call_id: UUID, finalization_id: UUID, command_id: UUID
    ) -> dict[str, object]:
        finalization = await self._session.get(CallFinalization, finalization_id)
        if (
            finalization is None
            or finalization.call_id != call_id
            or finalization.status is not FinalizationStatus.PROCESSING
            or finalization.current_command_id != command_id
            or finalization.summary is not None
        ):
            raise FinalizationError("summary command is not current")
        return await self._conversation_context(call_id)

    async def _conversation_context(self, call_id: UUID) -> dict[str, object]:
        conversation = await self._session.scalar(
            select(Conversation).where(Conversation.call_session_id == call_id)
        )
        if conversation is None:
            raise FinalizationError("conversation not found")
        messages = list(
            await self._session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.sequence_number)
            )
        )
        return {
            "call_id": str(call_id),
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
                if not message.interrupted
            ],
        }

    async def action_plan(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> ManagedWebhookPostJsonPlan:
        call = await self._session.get(CallSession, call_id)
        finalization = await self._session.get(CallFinalization, finalization_id)
        if (
            call is None
            or finalization is None
            or finalization.call_id != call_id
            or finalization.status is not FinalizationStatus.PROCESSING
            or finalization.current_command_id != command_id
            or finalization.summary is None
            or finalization.next_action_index >= len(finalization.action_ids)
            or finalization.action_ids[finalization.next_action_index] != action_id
        ):
            raise FinalizationError("finalization context not found")
        config = await self._config(call)
        action = next(
            (item for item in config.post_call_actions if item.action_id == action_id),
            None,
        )
        if action is None:
            raise FinalizationError("post-call action not found")
        connection = await self._session.get(
            IntegrationConnection, action.execution.connection_id
        )
        if (
            connection is None
            or connection.tenant_id != call.tenant_id
            or connection.status is not IntegrationConnectionStatus.ACTIVE
            or connection.provider is not IntegrationProvider.MANAGED_WEBHOOK
        ):
            raise FinalizationError("post-call connection unavailable")
        context = await self._conversation_context(call_id)
        context["summary"] = finalization.summary
        payload = JsonataMappingEngine().evaluate(
            action.execution.request_mapping, context
        )
        return ManagedWebhookPostJsonPlan(
            plan_type="managed_webhook.post_json.v1",
            connection_ref=connection.credential_ref,
            operation_id=command_id,
            capability=ManagedWebhookCapability(
                semantic_key=action.semantic_key,
                semantic_version=action.semantic_version,
            ),
            payload=payload,
            timeout_seconds=action.execution.timeout_seconds,
        )

    async def _config(self, call: CallSession) -> TenantConfigV3:
        revision = await self._session.get(
            TenantConfigRevision, call.tenant_config_revision_id
        )
        if revision is None or revision.schema_version != 3:
            raise FinalizationError("pinned tenant configuration unavailable")
        return TenantConfigV3.model_validate(revision.config)
