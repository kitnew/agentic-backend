from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.runtime.finalization.models import FinalizationStatus
from backend_core.runtime.finalization.service import FinalizationService
from contracts import (
    CallEventPayload,
    CommandError,
    CommandResult,
    MessageEnvelope,
)


class Session:
    def __init__(self) -> None:
        self.scalars: list[object | None] = []
        self.call: CallSession | None = None
        self.added = []

    async def scalar(self, query):
        return self.scalars.pop(0)

    async def get(self, model, key):
        return self.call

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class Commands:
    def __init__(self) -> None:
        self.sent: list[MessageEnvelope] = []

    async def send(self, command: MessageEnvelope) -> None:
        self.sent.append(command)


class Service(FinalizationService):
    def __init__(self, session: Session, commands: Commands, actions: list[str]):
        super().__init__(session, commands)  # type: ignore[arg-type]
        self.actions = actions

    async def _config(self, call):
        return SimpleNamespace(
            post_call_actions=[SimpleNamespace(action_id=value) for value in self.actions]
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
        payload=CallEventPayload(call_id=call.id, status="ended").model_dump(mode="json"),
    )


def result_envelope(result: CommandResult) -> MessageEnvelope:
    return MessageEnvelope(
        message_kind="command_result",
        message_type="command.result",
        correlation_id=uuid4(),
        payload=result.model_dump(mode="json"),
    )


@pytest.mark.asyncio
async def test_call_ended_starts_summary_then_actions_and_completes() -> None:
    session = Session()
    session.scalars = [None]
    session.call = ended_call()
    commands = Commands()
    service = Service(session, commands, ["notify"])

    finalization = await service.start(ended_event(session.call))

    assert finalization.status is FinalizationStatus.PROCESSING
    assert commands.sent[0].message_type == "call.generate_summary.v1"
    summary_id = commands.sent[0].message_id
    session.scalars = [finalization]
    await service.handle_result(
        result_envelope(
            CommandResult(
                command_id=summary_id,
                command_type="call.generate_summary.v1",
                status="succeeded",
                output={"summary": "A concise summary"},
                attempt=1,
            )
        ),
        CommandResult(
            command_id=summary_id,
            command_type="call.generate_summary.v1",
            status="succeeded",
            output={"summary": "A concise summary"},
            attempt=1,
        ),
    )
    assert commands.sent[1].message_type == "call.execute_post_call_action.v1"
    action_id = commands.sent[1].message_id
    session.scalars = [finalization]
    action_result = CommandResult(
        command_id=action_id,
        command_type="call.execute_post_call_action.v1",
        status="succeeded",
        output={"deduplicated": False},
        attempt=1,
    )
    await service.handle_result(result_envelope(action_result), action_result)

    assert finalization.status is FinalizationStatus.COMPLETED
    assert finalization.summary == "A concise summary"
    assert not hasattr(finalization, "recording_status")


@pytest.mark.asyncio
async def test_terminal_command_failure_fails_finalization_not_call() -> None:
    session = Session()
    session.scalars = [None]
    session.call = ended_call()
    commands = Commands()
    service = Service(session, commands, [])
    finalization = await service.start(ended_event(session.call))
    command_id = commands.sent[0].message_id
    failed = CommandResult(
        command_id=command_id,
        command_type="call.generate_summary.v1",
        status="failed",
        error=CommandError(code="provider_failed", message="failed", transient=False),
        attempt=1,
    )
    session.scalars = [finalization]

    await service.handle_result(result_envelope(failed), failed)

    assert finalization.status is FinalizationStatus.FAILED
    assert session.call.status is CallSessionStatus.ENDED
