import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from contracts import (
    CallEventPayload,
    CommandResult,
    ExecutePostCallAction,
    GenerateCallSummary,
    ManagedWebhookBodyBinding,
    ManagedWebhookCapability,
    ManagedWebhookPostJsonPlan,
    MaterializeArtifactRepresentation,
    MessageEnvelope,
    PostCallAction,
    PostCallActionInput,
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
    ArtifactRepresentation,
    CallFinalization,
    CallRecording,
    FinalizationStatus,
    PostCallActionExecution,
    WorkStatus,
)


class FinalizationError(ValueError):
    pass


_BODY_REFERENCE_KEY = "artifact_representation_id"


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
        )
        self._session.add(finalization)
        self._session.add_all(
            PostCallActionExecution(
                finalization_id=finalization.id,
                action_id=action.action_id,
                status=WorkStatus.PENDING,
            )
            for action in config.post_call_actions
        )
        await self._session.flush()
        command = command_envelope(
            GenerateCallSummary(call_id=call.id, finalization_id=finalization.id),
            tenant_id=call.tenant_id,
            correlation_id=call.id,
            causation_id=event.message_id,
        )
        finalization.summary_command_id = command.message_id
        await self._commands.send(command)
        await self._schedule(finalization, event.message_id)
        return finalization

    async def handle_result(
        self, envelope: MessageEnvelope, result: CommandResult
    ) -> CallFinalization | None:
        finalization = await self._session.scalar(
            select(CallFinalization).where(
                CallFinalization.summary_command_id == result.command_id
            )
        )
        action_execution = None
        representation = None
        if finalization is None:
            action_execution = await self._session.scalar(
                select(PostCallActionExecution).where(
                    PostCallActionExecution.command_id == result.command_id
                )
            )
            if action_execution is not None:
                finalization = await self._session.get(
                    CallFinalization, action_execution.finalization_id
                )
        if finalization is None:
            representation = await self._session.scalar(
                select(ArtifactRepresentation).where(
                    ArtifactRepresentation.command_id == result.command_id
                )
            )
            if representation is not None:
                finalization = await self._session.scalar(
                    select(CallFinalization).where(
                        CallFinalization.call_id == representation.call_id
                    )
                )
        if finalization is None:
            return None
        finalization = await self._session.scalar(
            select(CallFinalization)
            .where(CallFinalization.id == finalization.id)
            .with_for_update()
        )
        if (
            finalization is None
            or finalization.status is not FinalizationStatus.PROCESSING
        ):
            return finalization
        expected_type = (
            "call.execute_post_call_action.v1"
            if action_execution is not None
            else "artifact.materialize_representation.v1"
            if representation is not None
            else "call.generate_summary.v1"
        )
        if result.command_type != expected_type:
            raise FinalizationError("command result does not match scheduled work")
        if result.status == "failed":
            assert result.error is not None
            error = f"{result.error.code}: {result.error.message}"[:1000]
            if action_execution is not None:
                action_execution.status = WorkStatus.FAILED
                action_execution.last_error = error
                action_execution.completed_at = datetime.now(UTC)
            if representation is not None:
                representation.status = WorkStatus.FAILED
                representation.last_error = error
                representation.completed_at = datetime.now(UTC)
            self._fail(finalization, error)
            return finalization
        if result.command_type == "call.generate_summary.v1":
            if finalization.summary_command_id != result.command_id:
                raise FinalizationError("summary command result is not current")
            assert result.output is not None
            summary = result.output.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise FinalizationError("summary result is invalid")
            finalization.summary = summary.strip()
            finalization.summary_command_id = None
        elif result.command_type == "call.execute_post_call_action.v1":
            if (
                action_execution is None
                or action_execution.status is not WorkStatus.PROCESSING
            ):
                raise FinalizationError("action command result is not current")
            action_execution.status = WorkStatus.COMPLETED
            action_execution.completed_at = datetime.now(UTC)
        elif result.command_type == "artifact.materialize_representation.v1":
            if (
                representation is None
                or representation.status is not WorkStatus.PROCESSING
            ):
                raise FinalizationError("representation command result is not current")
            assert result.output is not None
            if (
                result.output.get("representation_id") != str(representation.id)
                or result.output.get("byte_size") != representation.byte_size
                or result.output.get("sha256") != representation.sha256
                or representation.content is None
            ):
                raise FinalizationError("representation result is invalid")
            representation.status = WorkStatus.COMPLETED
            representation.completed_at = datetime.now(UTC)
        else:
            raise FinalizationError("unsupported command result")
        await self._schedule(finalization, envelope.message_id)
        return finalization

    async def summary_context(
        self, call_id: UUID, finalization_id: UUID, command_id: UUID
    ) -> dict[str, object]:
        finalization = await self._session.get(CallFinalization, finalization_id)
        if (
            finalization is None
            or finalization.call_id != call_id
            or finalization.status is not FinalizationStatus.PROCESSING
            or finalization.summary_command_id != command_id
            or finalization.summary is not None
        ):
            raise FinalizationError("summary command is not current")
        return await self._conversation_context(call_id)

    async def action_plan(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> ManagedWebhookPostJsonPlan:
        call = await self._session.get(CallSession, call_id)
        finalization = await self._session.get(CallFinalization, finalization_id)
        execution = await self._session.scalar(
            select(PostCallActionExecution).where(
                PostCallActionExecution.finalization_id == finalization_id,
                PostCallActionExecution.action_id == action_id,
            )
        )
        if (
            call is None
            or finalization is None
            or finalization.call_id != call_id
            or finalization.status is not FinalizationStatus.PROCESSING
            or execution is None
            or execution.status is not WorkStatus.PROCESSING
            or execution.command_id != command_id
        ):
            raise FinalizationError("finalization context not found")
        action = self._action(await self._config(call), action_id)
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
        inputs: dict[str, object] = {}
        available_bodies: set[UUID] = set()
        for name, requested in action.inputs.items():
            inputs[name], body_ids = await self._mapping_input(finalization, requested)
            available_bodies.update(body_ids)
        context = await self._mapping_context(call, inputs)
        payload = JsonataMappingEngine().evaluate(
            action.execution.request_mapping, context
        )
        payload, body_bindings = self._body_bindings(payload)
        if (
            not {binding.representation_id for binding in body_bindings}
            <= available_bodies
        ):
            raise FinalizationError("action references an unavailable artifact body")
        return ManagedWebhookPostJsonPlan(
            plan_type="managed_webhook.post_json.v1",
            connection_ref=connection.credential_ref,
            operation_id=command_id,
            capability=ManagedWebhookCapability(
                semantic_key=action.semantic_key,
                semantic_version=action.semantic_version,
            ),
            payload=payload,
            body_bindings=body_bindings,
            timeout_seconds=action.execution.timeout_seconds,
        )

    async def persist_recording(
        self, call_id: UUID, content: bytes, content_type: str
    ) -> CallRecording:
        call = await self._session.get(CallSession, call_id)
        if call is None:
            raise FinalizationError("call not found")
        digest = sha256(content).hexdigest()
        existing = await self._session.scalar(
            select(CallRecording)
            .where(CallRecording.call_id == call_id)
            .with_for_update()
        )
        if existing is not None:
            if existing.sha256 != digest:
                raise FinalizationError(
                    "recording already persisted with different content"
                )
            return existing
        recording = CallRecording(
            tenant_id=call.tenant_id,
            call_id=call.id,
            content=content,
            content_type=content_type,
            byte_size=len(content),
            sha256=digest,
        )
        self._session.add(recording)
        await self._session.flush()
        finalization = await self._session.scalar(
            select(CallFinalization)
            .where(CallFinalization.call_id == call_id)
            .with_for_update()
        )
        if (
            finalization is not None
            and finalization.status is FinalizationStatus.PROCESSING
        ):
            await self._schedule(finalization, recording.id)
        return recording

    async def materialization_source(
        self, representation_id: UUID, command_id: UUID
    ) -> tuple[ArtifactRepresentation, bytes, str]:
        representation = await self._session.get(
            ArtifactRepresentation, representation_id
        )
        if (
            representation is None
            or representation.command_id != command_id
            or representation.status is not WorkStatus.PROCESSING
        ):
            raise FinalizationError("representation command is not current")
        if representation.artifact_type == "call_recording":
            recording = await self._session.scalar(
                select(CallRecording).where(
                    CallRecording.call_id == representation.call_id
                )
            )
            if recording is None:
                raise FinalizationError("recording not found")
            return representation, recording.content, recording.content_type
        transcript = await self._transcript(representation.call_id)
        return (
            representation,
            json.dumps(transcript, ensure_ascii=False).encode(),
            "application/json",
        )

    async def representation_content(
        self, representation_id: UUID, command_id: UUID
    ) -> tuple[ArtifactRepresentation, bytes]:
        execution = await self._session.scalar(
            select(PostCallActionExecution).where(
                PostCallActionExecution.command_id == command_id
            )
        )
        representation = await self._session.get(
            ArtifactRepresentation, representation_id
        )
        if (
            execution is None
            or execution.status is not WorkStatus.PROCESSING
            or representation is None
            or representation.status is not WorkStatus.COMPLETED
            or representation.content is None
        ):
            raise FinalizationError("artifact representation is unavailable")
        finalization = await self._session.get(
            CallFinalization, execution.finalization_id
        )
        call = (
            await self._session.get(CallSession, finalization.call_id)
            if finalization
            else None
        )
        if call is None or representation.call_id != call.id:
            raise FinalizationError("artifact representation is unavailable")
        action = self._action(await self._config(call), execution.action_id)
        if not any(
            requested.artifact == representation.artifact_type
            and requested.representation == representation.representation
            for requested in action.inputs.values()
        ):
            raise FinalizationError("artifact representation is unavailable")
        return representation, representation.content

    async def store_representation(
        self,
        representation_id: UUID,
        command_id: UUID,
        content: bytes,
        content_type: str,
    ) -> ArtifactRepresentation:
        representation = await self._session.scalar(
            select(ArtifactRepresentation)
            .where(ArtifactRepresentation.id == representation_id)
            .with_for_update()
        )
        if (
            representation is None
            or representation.command_id != command_id
            or representation.status is not WorkStatus.PROCESSING
        ):
            raise FinalizationError("representation command is not current")
        digest = sha256(content).hexdigest()
        if representation.content is not None and representation.sha256 != digest:
            raise FinalizationError("representation content conflicts with retry")
        representation.content = content
        representation.content_type = content_type
        representation.byte_size = len(content)
        representation.sha256 = digest
        await self._session.flush()
        return representation

    async def _schedule(
        self, finalization: CallFinalization, causation_id: UUID
    ) -> None:
        call = await self._session.get(CallSession, finalization.call_id)
        if call is None:
            raise FinalizationError("call not found")
        config = await self._config(call)
        executions = list(
            await self._session.scalars(
                select(PostCallActionExecution).where(
                    PostCallActionExecution.finalization_id == finalization.id
                )
            )
        )
        representations = {
            (item.artifact_type, item.representation): item
            for item in await self._session.scalars(
                select(ArtifactRepresentation).where(
                    ArtifactRepresentation.call_id == finalization.call_id
                )
            )
        }
        recording = await self._session.scalar(
            select(CallRecording).where(CallRecording.call_id == finalization.call_id)
        )
        by_id = {execution.action_id: execution for execution in executions}
        for action in config.post_call_actions:
            execution = by_id[action.action_id]
            if execution.status is not WorkStatus.PENDING:
                continue
            ready = True
            for requested in action.inputs.values():
                key = (requested.artifact, requested.representation)
                stored = representations.get(key)
                if self._input_ready(finalization, requested, recording, stored):
                    continue
                ready = False
                if stored is not None and stored.status is WorkStatus.FAILED:
                    self._fail(
                        finalization, stored.last_error or "representation failed"
                    )
                    return
                if stored is None and self._source_ready(requested, recording):
                    representations[key] = await self._materialize(
                        finalization, requested, causation_id
                    )
            if ready:
                command = command_envelope(
                    ExecutePostCallAction(
                        call_id=finalization.call_id,
                        finalization_id=finalization.id,
                        action_id=action.action_id,
                    ),
                    tenant_id=finalization.tenant_id,
                    correlation_id=finalization.call_id,
                    causation_id=causation_id,
                )
                execution.status = WorkStatus.PROCESSING
                execution.command_id = command.message_id
                await self._commands.send(command)
        if finalization.summary is not None and all(
            execution.status is WorkStatus.COMPLETED for execution in executions
        ):
            finalization.status = FinalizationStatus.COMPLETED
            finalization.completed_at = datetime.now(UTC)

    async def _materialize(
        self,
        finalization: CallFinalization,
        requested: PostCallActionInput,
        causation_id: UUID,
    ) -> ArtifactRepresentation:
        representation_id = uuid4()
        command = command_envelope(
            MaterializeArtifactRepresentation(
                call_id=finalization.call_id,
                finalization_id=finalization.id,
                representation_id=representation_id,
            ),
            tenant_id=finalization.tenant_id,
            correlation_id=finalization.call_id,
            causation_id=causation_id,
        )
        representation = ArtifactRepresentation(
            id=representation_id,
            tenant_id=finalization.tenant_id,
            call_id=finalization.call_id,
            artifact_type=requested.artifact,
            representation=requested.representation,
            status=WorkStatus.PROCESSING,
            command_id=command.message_id,
        )
        self._session.add(representation)
        await self._session.flush()
        await self._commands.send(command)
        return representation

    @staticmethod
    def _input_ready(
        finalization: CallFinalization,
        requested: PostCallActionInput,
        recording: CallRecording | None,
        stored: ArtifactRepresentation | None,
    ) -> bool:
        if (
            requested.artifact == "transcript"
            and requested.representation == "raw_json"
        ):
            return True
        if requested.artifact == "call_summary":
            return finalization.summary is not None
        if (
            requested.artifact == "call_recording"
            and requested.representation == "original"
        ):
            return recording is not None
        return stored is not None and stored.status is WorkStatus.COMPLETED

    @staticmethod
    def _source_ready(
        requested: PostCallActionInput, recording: CallRecording | None
    ) -> bool:
        return requested.artifact == "transcript" or (
            requested.artifact == "call_recording" and recording is not None
        )

    async def _input_value(
        self, finalization: CallFinalization, requested: PostCallActionInput
    ) -> object:
        if (
            requested.artifact == "transcript"
            and requested.representation == "raw_json"
        ):
            return await self._transcript(finalization.call_id)
        if requested.artifact == "call_summary":
            if finalization.summary is None:
                raise FinalizationError("summary representation is unavailable")
            return finalization.summary
        if (
            requested.artifact == "call_recording"
            and requested.representation == "original"
        ):
            recording = await self._session.scalar(
                select(CallRecording).where(
                    CallRecording.call_id == finalization.call_id
                )
            )
            if recording is None:
                raise FinalizationError("recording representation is unavailable")
            return {
                "recording_id": str(recording.id),
                "content_type": recording.content_type,
                "byte_size": recording.byte_size,
                "sha256": recording.sha256,
            }
        stored = await self._session.scalar(
            select(ArtifactRepresentation).where(
                ArtifactRepresentation.call_id == finalization.call_id,
                ArtifactRepresentation.artifact_type == requested.artifact,
                ArtifactRepresentation.representation == requested.representation,
                ArtifactRepresentation.status == WorkStatus.COMPLETED,
            )
        )
        if stored is None or stored.content is None:
            raise FinalizationError("artifact representation is unavailable")
        return stored.content.decode()

    async def _mapping_input(
        self, finalization: CallFinalization, requested: PostCallActionInput
    ) -> tuple[object, set[UUID]]:
        if requested.representation == "base64_text":
            stored = await self._session.scalar(
                select(ArtifactRepresentation).where(
                    ArtifactRepresentation.call_id == finalization.call_id,
                    ArtifactRepresentation.artifact_type == requested.artifact,
                    ArtifactRepresentation.representation == requested.representation,
                    ArtifactRepresentation.status == WorkStatus.COMPLETED,
                )
            )
            if stored is None:
                raise FinalizationError("artifact representation is unavailable")
            return (
                {
                    "artifact": stored.artifact_type,
                    "representation": stored.representation,
                    "representation_id": str(stored.id),
                    "content_type": stored.content_type,
                    "byte_size": stored.byte_size,
                    "sha256": stored.sha256,
                    "body": {_BODY_REFERENCE_KEY: str(stored.id)},
                },
                {stored.id},
            )
        return (
            {
                "artifact": requested.artifact,
                "representation": requested.representation,
                "value": await self._input_value(finalization, requested),
            },
            set(),
        )

    @staticmethod
    def _body_bindings(
        value: object, path: str = ""
    ) -> tuple[dict[str, object], list[ManagedWebhookBodyBinding]]:
        if not isinstance(value, dict):
            raise FinalizationError("post-call mapping must return an object")

        def visit(
            item: object, item_path: str
        ) -> tuple[object, list[ManagedWebhookBodyBinding]]:
            if isinstance(item, dict):
                if set(item) == {_BODY_REFERENCE_KEY}:
                    try:
                        return None, [
                            ManagedWebhookBodyBinding(
                                representation_id=UUID(str(item[_BODY_REFERENCE_KEY])),
                                payload_path=item_path,
                            )
                        ]
                    except ValueError as error:
                        raise FinalizationError(
                            "artifact body reference is invalid"
                        ) from error
                mapped: dict[str, object] = {}
                bindings: list[ManagedWebhookBodyBinding] = []
                for key, child in item.items():
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    mapped[key], child_bindings = visit(child, f"{item_path}/{escaped}")
                    bindings.extend(child_bindings)
                return mapped, bindings
            if isinstance(item, list):
                mapped_list: list[object] = []
                bindings = []
                for index, child in enumerate(item):
                    mapped_item, child_bindings = visit(child, f"{item_path}/{index}")
                    mapped_list.append(mapped_item)
                    bindings.extend(child_bindings)
                return mapped_list, bindings
            return item, []

        payload, bindings = visit(value, path)
        assert isinstance(payload, dict)
        return payload, bindings

    async def _conversation_context(self, call_id: UUID) -> dict[str, object]:
        return {"call_id": str(call_id), "messages": await self._transcript(call_id)}

    async def _mapping_context(
        self, call: CallSession, inputs: dict[str, object]
    ) -> dict[str, object]:
        conversation = await self._session.scalar(
            select(Conversation).where(Conversation.call_session_id == call.id)
        )
        if conversation is None:
            raise FinalizationError("conversation not found")
        config = await self._config(call)
        return {
            "call_id": str(call.id),
            "call": {
                "id": str(call.id),
                "conversation_id": str(conversation.id),
                "caller_number": call.caller_phone_e164,
                "started_at": call.started_at.isoformat() if call.started_at else None,
                "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            },
            "agent": {
                "id": config.agent.profile,
                "name": config.agent.display_name,
            },
            "inputs": inputs,
        }

    async def _transcript(self, call_id: UUID) -> list[dict[str, str]]:
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
        return [
            {"role": message.role.value, "content": message.content}
            for message in messages
            if not message.interrupted
        ]

    @staticmethod
    def _action(config: TenantConfigV3, action_id: str) -> PostCallAction:
        action = next(
            (item for item in config.post_call_actions if item.action_id == action_id),
            None,
        )
        if action is None:
            raise FinalizationError("post-call action not found")
        return action

    @staticmethod
    def _fail(finalization: CallFinalization, error: str) -> None:
        finalization.status = FinalizationStatus.FAILED
        finalization.last_error = error[:1000]
        finalization.completed_at = datetime.now(UTC)

    async def _config(self, call: CallSession) -> TenantConfigV3:
        revision = await self._session.get(
            TenantConfigRevision, call.tenant_config_revision_id
        )
        if revision is None or revision.schema_version != 3:
            raise FinalizationError("pinned tenant configuration unavailable")
        return TenantConfigV3.model_validate(revision.config)
