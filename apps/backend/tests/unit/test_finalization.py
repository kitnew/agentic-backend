from types import SimpleNamespace
from uuid import UUID, uuid4

import backend_core.runtime.finalization.service as finalization_service
import pytest
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationProvider,
)
from backend_core.modules.tenants.models import TenantConfigRevision
from backend_core.runtime.finalization.models import (
    ArtifactRepresentation,
    CallFinalization,
    CallRecording,
    FinalizationStatus,
    PostCallActionExecution,
    WorkStatus,
)
from backend_core.runtime.finalization.service import FinalizationService
from contracts import (
    CallEventPayload,
    CommandError,
    CommandResult,
    MessageEnvelope,
    PostCallAction,
    PostCallActionInput,
)


class Session:
    def __init__(self, call: CallSession) -> None:
        self.call = call
        self.finalization: CallFinalization | None = None
        self.recording: CallRecording | None = None
        self.actions: list[PostCallActionExecution] = []
        self.representations: list[ArtifactRepresentation] = []
        self.revisions: dict[UUID, object] = {}
        self.connections: dict[UUID, IntegrationConnection] = {}

    @staticmethod
    def _query(query) -> tuple[type, str, list[object]]:
        return (
            query.column_descriptions[0]["entity"],
            str(query.whereclause),
            list(query.compile().params.values()),
        )

    async def scalar(self, query):
        model, where, values = self._query(query)
        if model is CallFinalization:
            if self.finalization is None:
                return None
            if "summary_command_id" in where:
                return (
                    self.finalization
                    if self.finalization.summary_command_id in values
                    else None
                )
            if "call_id" in where:
                return (
                    self.finalization if self.finalization.call_id in values else None
                )
            return self.finalization
        if model is CallRecording:
            return self.recording
        if model is PostCallActionExecution:
            return self._matching(self.actions, values)
        if model is ArtifactRepresentation:
            return self._matching(self.representations, values)
        return None

    async def scalars(self, query):
        model = query.column_descriptions[0]["entity"]
        if model is PostCallActionExecution:
            return self.actions
        if model is ArtifactRepresentation:
            return self.representations
        return []

    @staticmethod
    def _matching(items, values):
        for item in items:
            attributes = {
                item.id,
                getattr(item, "command_id", None),
                getattr(item, "action_id", None),
                getattr(item, "finalization_id", None),
                getattr(item, "call_id", None),
                getattr(item, "artifact_type", None),
                getattr(item, "representation", None),
                getattr(item, "status", None),
            }
            if all(
                value in attributes or not isinstance(value, (UUID, str))
                for value in values
            ):
                return item
        return None

    async def get(self, model, key):
        if model is CallSession:
            return self.call if key == self.call.id else None
        if model is CallFinalization:
            return (
                self.finalization
                if self.finalization and key == self.finalization.id
                else None
            )
        if model is ArtifactRepresentation:
            return next((item for item in self.representations if item.id == key), None)
        if model is TenantConfigRevision:
            return self.revisions.get(key)
        if model is IntegrationConnection:
            return self.connections.get(key)
        return None

    def add(self, value) -> None:
        if isinstance(value, CallFinalization):
            self.finalization = value
        elif isinstance(value, CallRecording):
            self.recording = value
        elif isinstance(value, ArtifactRepresentation):
            self.representations.append(value)

    def add_all(self, values) -> None:
        self.actions.extend(values)

    async def flush(self) -> None:
        return None


class Commands:
    def __init__(self) -> None:
        self.sent: list[MessageEnvelope] = []

    async def send(self, command: MessageEnvelope) -> None:
        self.sent.append(command)


class Service(FinalizationService):
    def __init__(
        self, session: Session, commands: Commands, actions: list[PostCallAction]
    ) -> None:
        super().__init__(session, commands)  # type: ignore[arg-type]
        self.actions = actions

    async def _config(self, call):
        return SimpleNamespace(post_call_actions=self.actions)


def action(
    action_id: str,
    inputs: dict[str, dict[str, str]] | None = None,
    request_mapping: str = "{}",
) -> PostCallAction:
    return PostCallAction.model_validate(
        {
            "action_id": action_id,
            "type": "http.post_json",
            "inputs": inputs or {},
            "semantic_key": f"post_call.{action_id}",
            "semantic_version": 1,
            "execution": {
                "plan_type": "managed_webhook.post_json.v1",
                "connection_id": str(uuid4()),
                "mapping_language": "jsonata",
                "mapping_contract_version": 1,
                "mapping_engine": "jsonata-python",
                "mapping_engine_version": "0.7.0",
                "request_mapping": request_mapping,
                "timeout_seconds": 10,
            },
        }
    )


def ended_call() -> CallSession:
    return CallSession(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_config_revision_id=uuid4(),
        prompt_set_revision_id=uuid4(),
        voice_runtime_revision_id=uuid4(),
        channel=CallChannel.WEB,
        direction=CallDirection.INBOUND,
        provider="livekit",
        provider_call_id=str(uuid4()),
        room_name="room",
        status=CallSessionStatus.ENDED,
    )


def ended_event(call: CallSession) -> MessageEnvelope:
    return MessageEnvelope(
        message_kind="event",
        message_type="call.ended",
        correlation_id=call.id,
        tenant_id=call.tenant_id,
        payload=CallEventPayload(call_id=call.id, status="ended").model_dump(
            mode="json"
        ),
    )


def connection(call: CallSession, configured: PostCallAction) -> IntegrationConnection:
    return IntegrationConnection(
        id=configured.execution.connection_id,
        tenant_id=call.tenant_id,
        key="hook",
        provider=IntegrationProvider.MANAGED_WEBHOOK,
        credential_ref="tenant-hook",
        status=IntegrationConnectionStatus.ACTIVE,
    )


def result_envelope(result: CommandResult) -> MessageEnvelope:
    return MessageEnvelope(
        message_kind="command_result",
        message_type="command.result",
        correlation_id=uuid4(),
        payload=result.model_dump(mode="json"),
    )


def command_result(
    command: MessageEnvelope, output: dict[str, object]
) -> CommandResult:
    return CommandResult(
        command_id=command.message_id,
        command_type=command.message_type,  # type: ignore[arg-type]
        status="succeeded",
        output=output,
        attempt=1,
    )


@pytest.mark.asyncio
async def test_no_input_and_transcript_actions_run_independently_at_start() -> None:
    call = ended_call()
    session = Session(call)
    commands = Commands()
    service = Service(
        session,
        commands,
        [
            action("notify"),
            action(
                "transcript",
                {
                    "transcript": {
                        "artifact": "transcript",
                        "representation": "raw_json",
                    }
                },
            ),
        ],
    )

    finalization = await service.start(ended_event(call))

    assert finalization.status is FinalizationStatus.PROCESSING
    assert [item.message_type for item in commands.sent] == [
        "call.generate_summary.v1",
        "call.execute_post_call_action.v1",
        "call.execute_post_call_action.v1",
    ]


@pytest.mark.asyncio
async def test_action_waits_for_recording_and_missing_representation_is_materialized() -> (
    None
):
    call = ended_call()
    session = Session(call)
    commands = Commands()
    service = Service(
        session,
        commands,
        [
            action(
                "recording",
                {
                    "recording": {
                        "artifact": "call_recording",
                        "representation": "base64_text",
                    }
                },
            )
        ],
    )

    await service.start(ended_event(call))
    assert [item.message_type for item in commands.sent] == ["call.generate_summary.v1"]

    await service.persist_recording(call.id, b"audio", "audio/ogg")

    assert commands.sent[-1].message_type == "artifact.materialize_representation.v1"
    assert len(session.representations) == 1
    assert session.representations[0].content is None


@pytest.mark.asyncio
async def test_existing_and_successful_representation_make_action_runnable() -> None:
    call = ended_call()
    session = Session(call)
    session.recording = CallRecording(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        content=b"audio",
        content_type="audio/ogg",
        byte_size=5,
        sha256="digest",
    )
    commands = Commands()
    service = Service(
        session,
        commands,
        [
            action(
                "recording",
                {
                    "recording": {
                        "artifact": "call_recording",
                        "representation": "base64_text",
                    }
                },
            )
        ],
    )

    await service.start(ended_event(call))
    materialize = commands.sent[-1]
    representation = session.representations[0]
    await service.store_representation(
        representation.id, materialize.message_id, b"YXVkaW8=", "text/plain"
    )
    result = command_result(
        materialize,
        {
            "representation_id": str(representation.id),
            "byte_size": representation.byte_size,
            "sha256": representation.sha256,
        },
    )

    await service.handle_result(result_envelope(result), result)

    assert representation.status is WorkStatus.COMPLETED
    assert commands.sent[-1].message_type == "call.execute_post_call_action.v1"
    assert "content" not in materialize.payload


@pytest.mark.asyncio
async def test_existing_representation_is_reused_without_materialization() -> None:
    call = ended_call()
    session = Session(call)
    session.recording = CallRecording(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        content=b"audio",
        content_type="audio/ogg",
        byte_size=5,
        sha256="digest",
    )
    session.representations.append(
        ArtifactRepresentation(
            id=uuid4(),
            tenant_id=call.tenant_id,
            call_id=call.id,
            artifact_type="call_recording",
            representation="base64_text",
            status=WorkStatus.COMPLETED,
            command_id=uuid4(),
            content=b"YXVkaW8=",
            content_type="text/plain",
            byte_size=8,
            sha256="stored",
        )
    )
    commands = Commands()
    service = Service(
        session,
        commands,
        [
            action(
                "recording",
                {
                    "recording": {
                        "artifact": "call_recording",
                        "representation": "base64_text",
                    }
                },
            )
        ],
    )

    await service.start(ended_event(call))

    assert [item.message_type for item in commands.sent] == [
        "call.generate_summary.v1",
        "call.execute_post_call_action.v1",
    ]


@pytest.mark.asyncio
async def test_action_retries_read_the_same_stored_representation() -> None:
    call = ended_call()
    session = Session(call)
    representation = ArtifactRepresentation(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        artifact_type="call_recording",
        representation="base64_text",
        status=WorkStatus.COMPLETED,
        command_id=uuid4(),
        content=b"YXVkaW8=",
        content_type="text/plain",
        byte_size=8,
        sha256="stored",
    )
    session.representations.append(representation)
    finalization = CallFinalization(
        id=uuid4(),
        call_id=call.id,
        tenant_id=call.tenant_id,
        status=FinalizationStatus.PROCESSING,
    )
    requested = PostCallActionInput(
        artifact="call_recording", representation="base64_text"
    )
    service = Service(session, Commands(), [])

    first = await service._input_value(finalization, requested)
    second = await service._input_value(finalization, requested)

    assert first == second == "YXVkaW8="
    assert session.representations == [representation]


@pytest.mark.asyncio
async def test_large_representation_is_a_body_binding_not_jsonata_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ended_call()
    configured = action(
        "recording",
        {
            "recording": {
                "artifact": "call_recording",
                "representation": "base64_text",
            }
        },
        '{"recording": inputs.recording.body}',
    )
    session = Session(call)
    session.connections[configured.execution.connection_id] = connection(
        call, configured
    )
    finalization = CallFinalization(
        id=uuid4(),
        call_id=call.id,
        tenant_id=call.tenant_id,
        status=FinalizationStatus.PROCESSING,
    )
    command_id = uuid4()
    session.finalization = finalization
    session.actions.append(
        PostCallActionExecution(
            finalization_id=finalization.id,
            action_id=configured.action_id,
            status=WorkStatus.PROCESSING,
            command_id=command_id,
        )
    )
    representation = ArtifactRepresentation(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        artifact_type="call_recording",
        representation="base64_text",
        status=WorkStatus.COMPLETED,
        command_id=uuid4(),
        content=b"must-not-enter-jsonata",
        content_type="text/plain",
        byte_size=64_001,
        sha256="stored",
    )
    session.representations.append(representation)
    captured: dict[str, object] = {}

    class Mapping:
        def evaluate(self, expression, data):
            captured.update(data)
            return {"recording": data["inputs"]["recording"]["body"]}

    monkeypatch.setattr(finalization_service, "JsonataMappingEngine", Mapping)
    plan = await Service(session, Commands(), [configured]).action_plan(
        call.id, finalization.id, configured.action_id, command_id
    )

    assert captured["inputs"] == {
        "recording": {
            "artifact": "call_recording",
            "representation": "base64_text",
            "representation_id": str(representation.id),
            "content_type": "text/plain",
            "byte_size": 64_001,
            "sha256": "stored",
            "body": {"artifact_representation_id": str(representation.id)},
        }
    }
    assert representation.content is not None
    assert representation.content.decode() not in str(captured)
    assert plan.payload == {"recording": None}
    assert plan.body_bindings[0].representation_id == representation.id
    assert plan.body_bindings[0].payload_path == "/recording"


@pytest.mark.asyncio
async def test_small_post_call_payload_still_uses_jsonata() -> None:
    call = ended_call()
    configured = action("notify", request_mapping='{"call": call_id}')
    session = Session(call)
    session.connections[configured.execution.connection_id] = connection(
        call, configured
    )
    finalization = CallFinalization(
        id=uuid4(),
        call_id=call.id,
        tenant_id=call.tenant_id,
        status=FinalizationStatus.PROCESSING,
    )
    command_id = uuid4()
    session.finalization = finalization
    session.actions.append(
        PostCallActionExecution(
            finalization_id=finalization.id,
            action_id=configured.action_id,
            status=WorkStatus.PROCESSING,
            command_id=command_id,
        )
    )

    plan = await Service(session, Commands(), [configured]).action_plan(
        call.id, finalization.id, configured.action_id, command_id
    )

    assert plan.payload == {"call": str(call.id)}
    assert plan.body_bindings == []


@pytest.mark.asyncio
async def test_finalized_call_requires_summary_and_all_actions() -> None:
    call = ended_call()
    session = Session(call)
    commands = Commands()
    service = Service(session, commands, [action("notify")])
    finalization = await service.start(ended_event(call))
    summary_command, action_command = commands.sent
    summary = command_result(summary_command, {"summary": "A concise summary"})
    await service.handle_result(result_envelope(summary), summary)
    assert finalization.status is FinalizationStatus.PROCESSING

    executed = command_result(action_command, {"deduplicated": False})
    await service.handle_result(result_envelope(executed), executed)

    assert finalization.status is FinalizationStatus.COMPLETED
    assert finalization.summary == "A concise summary"


@pytest.mark.asyncio
async def test_terminal_action_failure_fails_finalization_not_call() -> None:
    call = ended_call()
    session = Session(call)
    commands = Commands()
    service = Service(session, commands, [action("notify")])
    finalization = await service.start(ended_event(call))
    failed = CommandResult(
        command_id=commands.sent[1].message_id,
        command_type="call.execute_post_call_action.v1",
        status="failed",
        error=CommandError(code="provider_failed", message="failed", transient=False),
        attempt=1,
    )

    await service.handle_result(result_envelope(failed), failed)

    assert finalization.status is FinalizationStatus.FAILED
    assert session.actions[0].status is WorkStatus.FAILED
    assert call.status is CallSessionStatus.ENDED


@pytest.mark.asyncio
async def test_terminal_preparation_failure_fails_finalization_not_call() -> None:
    call = ended_call()
    session = Session(call)
    session.recording = CallRecording(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        content=b"audio",
        content_type="audio/ogg",
        byte_size=5,
        sha256="digest",
    )
    commands = Commands()
    service = Service(
        session,
        commands,
        [
            action(
                "recording",
                {
                    "recording": {
                        "artifact": "call_recording",
                        "representation": "base64_text",
                    }
                },
            )
        ],
    )
    finalization = await service.start(ended_event(call))
    materialize = commands.sent[-1]
    failed = CommandResult(
        command_id=materialize.message_id,
        command_type="artifact.materialize_representation.v1",
        status="failed",
        error=CommandError(code="storage_failed", message="failed", transient=False),
        attempt=1,
    )

    await service.handle_result(result_envelope(failed), failed)

    assert finalization.status is FinalizationStatus.FAILED
    assert session.representations[0].status is WorkStatus.FAILED
    assert call.status is CallSessionStatus.ENDED


@pytest.mark.asyncio
async def test_recording_is_persisted_without_tenant_action_configuration() -> None:
    call = ended_call()
    session = Session(call)
    service = Service(session, Commands(), [])

    first = await service.persist_recording(call.id, b"audio", "audio/ogg")
    second = await service.persist_recording(call.id, b"audio", "audio/ogg")

    assert first is second
    assert first.content == b"audio"


@pytest.mark.asyncio
async def test_config_resolution_uses_call_pinned_revision() -> None:
    call = ended_call()
    session = Session(call)
    pinned = {
        "schema_version": 3,
        "business": {"name": "Pinned", "type": "hotel"},
        "localization": {"default_locale": "en", "timezone": "UTC"},
        "agent": {"display_name": "A", "greeting": "Hi", "profile": "assistant"},
        "conversation": {"scope": "property_only"},
    }
    session.revisions[call.tenant_config_revision_id] = SimpleNamespace(
        schema_version=3, config=pinned
    )

    config = await FinalizationService(  # type: ignore[arg-type]
        session, Commands()
    )._config(call)

    assert config.business.name == "Pinned"
