import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from agentic_observability.domain import domain_span
from contracts import (
    CallEventPayload,
    CommandResult,
    ExecutePostCallAction,
    GenerateCallSummary,
    MaterializeArtifactRepresentation,
    MessageEnvelope,
    WorkerExecutionContext,
    command_envelope,
)
from opentelemetry.trace import Tracer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.application.messaging import CommandBus
from backend_core.modules.calls.models import CallSession
from backend_core.modules.conversations.models import Conversation, ConversationMessage
from backend_core.platform.control_plane import ControlPlaneClient
from backend_core.runtime.execution_context import ExecutionContextReader
from backend_core.runtime.finalization.models import (
    ArtifactRepresentation,
    CallFinalization,
    CallRecording,
    FinalizationStatus,
    PostCallActionExecution,
    RecordingStatus,
    WorkStatus,
)


class FinalizationError(ValueError):
    pass


_BODY_REFERENCE_KEY = "artifact_representation_id"


class FinalizationService:
    def __init__(
        self,
        session: AsyncSession,
        commands: CommandBus,
        tracer: Tracer | None = None,
        execution_context: ExecutionContextReader | None = None,
        control_plane: ControlPlaneClient | None = None,
    ) -> None:
        self._session = session
        self._commands = commands
        self._control_plane = control_plane
        self._tracer = tracer
        self._execution_context = execution_context

    async def control_plane_material(self, execution_id: UUID, integration_key: str):
        if self._control_plane is None:
            raise FinalizationError("integration material unavailable")
        return await self._control_plane.integration_execution_material(
            execution_id, integration_key
        )

    async def worker_context(
        self, call: CallSession, action_key: str
    ) -> WorkerExecutionContext:
        if self._execution_context is None:
            raise FinalizationError("execution context unavailable")
        return await self._execution_context.worker(call, action_key)

    async def start(self, event: MessageEnvelope) -> CallFinalization:
        with domain_span(
            self._tracer, "post_call.process", {"call.id": str(event.correlation_id)}
        ) as span:
            finalization = await self._start(event)
            if span is not None:
                span.set_attribute("tenant.id", str(finalization.tenant_id))
            return finalization

    async def _start(self, event: MessageEnvelope) -> CallFinalization:
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
        actions = await self._actions(call)
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
                action_id=str(action["key"]),
                status=WorkStatus.PENDING,
            )
            for action in actions
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

    async def recording_changed(self, event: MessageEnvelope) -> None:
        if event.message_type not in {"recording.ready", "recording.failed"}:
            raise FinalizationError("unsupported recording event")
        try:
            call_id = UUID(str(event.payload["call_id"]))
        except (KeyError, ValueError) as error:
            raise FinalizationError("recording event is invalid") from error
        finalization = await self._session.scalar(
            select(CallFinalization)
            .where(CallFinalization.call_id == call_id)
            .with_for_update()
        )
        if (
            finalization is not None
            and finalization.status is FinalizationStatus.PROCESSING
        ):
            await self._schedule(finalization, event.message_id)

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
                await self._schedule(finalization, envelope.message_id)
                return finalization
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

    async def action_context(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> dict[str, object]:
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
        action = self._action(await self._actions(call), action_id)
        inputs: dict[str, object] = {}
        for name, requested in self._artifact_inputs(action).items():
            inputs[name], _ = await self._mapping_input(finalization, requested)
        return {
            "worker_context": (await self.worker_context(call, action_id)).model_dump(
                mode="json"
            ),
            "mapping_context": await self._mapping_context(call, inputs),
        }

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
            raise FinalizationError("recording is materialized lazily by the worker")
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
        action = self._action(await self._actions(call), execution.action_id)
        if not any(
            requested["artifact"] == representation.artifact_type
            and requested["representation"] == representation.representation
            for requested in self._artifact_inputs(action).values()
        ):
            raise FinalizationError("artifact representation is unavailable")
        return representation, representation.content

    async def recording_source(
        self, representation_id: UUID, command_id: UUID
    ) -> tuple[ArtifactRepresentation, CallRecording]:
        representation = await self._authorized_representation(
            representation_id, command_id
        )
        if (
            representation.artifact_type != "call_recording"
            or representation.representation != "base64_text"
        ):
            raise FinalizationError("recording representation is unavailable")
        recording = await self._session.scalar(
            select(CallRecording).where(
                CallRecording.call_id == representation.call_id,
                CallRecording.status == RecordingStatus.READY,
            )
        )
        if recording is None:
            raise FinalizationError("recording representation is unavailable")
        return representation, recording

    async def _authorized_representation(
        self, representation_id: UUID, command_id: UUID
    ) -> ArtifactRepresentation:
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
        action = self._action(await self._actions(call), execution.action_id)
        if not any(
            requested["artifact"] == representation.artifact_type
            and requested["representation"] == representation.representation
            for requested in self._artifact_inputs(action).values()
        ):
            raise FinalizationError("artifact representation is unavailable")
        return representation

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
        actions = await self._actions(call)
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
        for action in actions:
            execution = by_id[str(action["key"])]
            if execution.status is not WorkStatus.PENDING:
                continue
            ready = True
            for requested in self._artifact_inputs(action).values():
                key = (str(requested["artifact"]), str(requested["representation"]))
                stored = representations.get(key)
                if self._input_ready(finalization, requested, recording, stored):
                    continue
                if (
                    recording is not None
                    and recording.status is RecordingStatus.FAILED
                    and requested["artifact"] == "call_recording"
                ):
                    self._fail(
                        finalization,
                        recording.error_code or "recording failed",
                    )
                    return
                if stored is not None and stored.status is WorkStatus.FAILED:
                    self._fail(
                        finalization, stored.last_error or "representation failed"
                    )
                    return
                if stored is None and self._source_ready(requested, recording):
                    representations[key] = await self._materialize(
                        finalization, requested, causation_id, recording
                    )
                    if representations[key].status is WorkStatus.COMPLETED:
                        continue
                ready = False
            if ready:
                command = command_envelope(
                    ExecutePostCallAction(
                        call_id=finalization.call_id,
                        finalization_id=finalization.id,
                        action_id=str(action["key"]),
                    ),
                    tenant_id=finalization.tenant_id,
                    correlation_id=finalization.call_id,
                    causation_id=causation_id,
                )
                execution.status = WorkStatus.PROCESSING
                execution.command_id = command.message_id
                await self._commands.send(command)
        if finalization.summary is not None and all(
            execution.status in {WorkStatus.COMPLETED, WorkStatus.FAILED}
            for execution in executions
        ):
            finalization.status = (
                FinalizationStatus.FAILED
                if any(
                    execution.status is WorkStatus.FAILED for execution in executions
                )
                else FinalizationStatus.COMPLETED
            )
            finalization.completed_at = datetime.now(UTC)

    async def _materialize(
        self,
        finalization: CallFinalization,
        requested: dict[str, object],
        causation_id: UUID,
        recording: CallRecording | None,
    ) -> ArtifactRepresentation:
        if requested["artifact"] == "call_recording":
            assert recording is not None and recording.byte_size is not None
            representation = ArtifactRepresentation(
                id=uuid4(),
                tenant_id=finalization.tenant_id,
                call_id=finalization.call_id,
                artifact_type="call_recording",
                representation="base64_text",
                status=WorkStatus.COMPLETED,
                command_id=uuid4(),
                content_type="text/plain; charset=utf-8",
                byte_size=((recording.byte_size + 2) // 3) * 4,
                completed_at=datetime.now(UTC),
            )
            self._session.add(representation)
            await self._session.flush()
            return representation
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
            artifact_type=str(requested["artifact"]),
            representation=str(requested["representation"]),
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
        requested: dict[str, object],
        recording: CallRecording | None,
        stored: ArtifactRepresentation | None,
    ) -> bool:
        if (
            requested["artifact"] == "transcript"
            and requested["representation"] == "raw_json"
        ):
            return True
        if requested["artifact"] == "call_summary":
            return finalization.summary is not None
        if (
            requested["artifact"] == "call_recording"
            and requested["representation"] == "original"
        ):
            return recording is not None and recording.status is RecordingStatus.READY
        return stored is not None and stored.status is WorkStatus.COMPLETED

    @staticmethod
    def _source_ready(
        requested: dict[str, object],
        recording: CallRecording | None,
    ) -> bool:
        return requested["artifact"] == "transcript" or (
            requested["artifact"] == "call_recording"
            and recording is not None
            and recording.status is RecordingStatus.READY
        )

    async def _input_value(
        self,
        finalization: CallFinalization,
        requested: dict[str, object],
    ) -> object:
        if (
            requested["artifact"] == "transcript"
            and requested["representation"] == "raw_json"
        ):
            return await self._transcript(finalization.call_id)
        if requested["artifact"] == "call_summary":
            if finalization.summary is None:
                raise FinalizationError("summary representation is unavailable")
            return finalization.summary
        if (
            requested["artifact"] == "call_recording"
            and requested["representation"] == "original"
        ):
            recording = await self._session.scalar(
                select(CallRecording).where(
                    CallRecording.call_id == finalization.call_id
                )
            )
            if recording is None or recording.status is not RecordingStatus.READY:
                raise FinalizationError("recording representation is unavailable")
            return {
                "recording_id": str(recording.id),
                "content_type": recording.content_type,
                "byte_size": recording.byte_size,
                "duration_ms": recording.duration_ms,
            }
        stored = await self._session.scalar(
            select(ArtifactRepresentation).where(
                ArtifactRepresentation.call_id == finalization.call_id,
                ArtifactRepresentation.artifact_type == requested["artifact"],
                ArtifactRepresentation.representation == requested["representation"],
                ArtifactRepresentation.status == WorkStatus.COMPLETED,
            )
        )
        if stored is None or stored.content is None:
            raise FinalizationError("artifact representation is unavailable")
        return stored.content.decode()

    async def _mapping_input(
        self,
        finalization: CallFinalization,
        requested: dict[str, object],
    ) -> tuple[object, set[UUID]]:
        if requested["representation"] == "base64_text":
            stored = await self._session.scalar(
                select(ArtifactRepresentation).where(
                    ArtifactRepresentation.call_id == finalization.call_id,
                    ArtifactRepresentation.artifact_type == requested["artifact"],
                    ArtifactRepresentation.representation
                    == requested["representation"],
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
                "artifact": requested["artifact"],
                "representation": requested["representation"],
                "value": await self._input_value(finalization, requested),
            },
            set(),
        )

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
        if self._execution_context is None:
            raise FinalizationError("execution context unavailable")
        voice = await self._execution_context.read(call)
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
                "id": voice.agent.get("personality"),
                "name": voice.agent.get("name"),
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
    def _action(actions: list[dict[str, object]], action_id: str) -> dict[str, object]:
        action = next(
            (item for item in actions if item.get("key") == action_id),
            None,
        )
        if action is None:
            raise FinalizationError("post-call action not found")
        return action

    @staticmethod
    def _artifact_inputs(action: dict[str, object]) -> dict[str, dict[str, object]]:
        definition = action.get("definition")
        inputs = (
            definition.get("artifact_inputs") if isinstance(definition, dict) else None
        )
        if not isinstance(inputs, dict) or not all(
            isinstance(value, dict) for value in inputs.values()
        ):
            raise FinalizationError("post-call action inputs are invalid")
        return inputs

    async def _actions(self, call: CallSession) -> list[dict[str, object]]:
        try:
            if self._execution_context is None:
                raise ValueError
            backend = self._execution_context.backend(call)
            actions = backend.backend_actions.get("post_call")
            if not isinstance(actions, list) or not all(
                isinstance(action, dict) for action in actions
            ):
                raise ValueError
            return actions
        except (AttributeError, ValueError) as error:
            raise FinalizationError("execution context unavailable") from error

    @staticmethod
    def _fail(finalization: CallFinalization, error: str) -> None:
        finalization.status = FinalizationStatus.FAILED
        finalization.last_error = error[:1000]
        finalization.completed_at = datetime.now(UTC)
