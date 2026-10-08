from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.events import call_event
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.runtime.finalization.models import (
    CallFinalization,
    FinalizationStatus,
    PostCallActionExecution,
    WorkStatus,
)
from backend_core.runtime.finalization.service import FinalizationService
from contracts import ConversationMessageRole, HandoffState


class _Session:
    async def get(self, model, key):
        return type("Call", (), {"id": key, "tenant_id": uuid4()})()

    async def scalars(self, query):
        if not hasattr(self, "_scalar_calls"):
            self._scalar_calls = 0
        self._scalar_calls += 1
        return self.executions if self._scalar_calls == 1 else []

    async def scalar(self, query):
        return None


class _Commands:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, command) -> None:
        self.sent.append(command)


@pytest.mark.asyncio
async def test_terminal_post_call_failure_does_not_block_next_ordered_action() -> None:
    call_id, finalization_id = uuid4(), uuid4()
    failed = PostCallActionExecution(
        finalization_id=finalization_id, action_id="first", status=WorkStatus.FAILED
    )
    next_action = PostCallActionExecution(
        finalization_id=finalization_id, action_id="second", status=WorkStatus.PENDING
    )
    session = _Session()
    session.executions = [failed, next_action]
    commands = _Commands()
    service = FinalizationService(session, commands)
    service._actions = lambda call: _actions()

    finalization = CallFinalization(
        id=finalization_id,
        call_id=call_id,
        tenant_id=uuid4(),
        status=FinalizationStatus.PROCESSING,
        summary="ready",
    )

    async def _actions():
        return [
            {"key": "first", "definition": {"artifact_inputs": {}}},
            {"key": "second", "definition": {"artifact_inputs": {}}},
        ]

    await service._schedule(finalization, uuid4())

    assert len(commands.sent) == 1
    assert commands.sent[0].payload["action_id"] == "second"
    assert finalization.status is FinalizationStatus.PROCESSING


@pytest.mark.asyncio
async def test_post_call_transcript_uses_canonical_conversation_sequence() -> None:
    class Session:
        async def scalar(self, query):
            return SimpleNamespace(id=uuid4())

        async def scalars(self, query):
            assert "sequence_number" in str(query)
            return [
                SimpleNamespace(
                    role=ConversationMessageRole.USER,
                    content="Dobrý deň",
                    interrupted=False,
                ),
                SimpleNamespace(
                    role=ConversationMessageRole.ASSISTANT,
                    content="Vitajte",
                    interrupted=False,
                ),
                SimpleNamespace(
                    role=ConversationMessageRole.ASSISTANT,
                    content="Vaša izba je pri",
                    interrupted=True,
                ),
                SimpleNamespace(
                    role=ConversationMessageRole.USER, content="draft", interrupted=True
                ),
            ]

    service = FinalizationService(Session(), _Commands())  # type: ignore[arg-type]
    assert await service._transcript(uuid4()) == [
        {"role": "user", "message": "Dobrý deň"},
        {"role": "agent", "message": "Vitajte"},
        {"role": "agent", "message": "Vaša izba je pri"},
    ]


@pytest.mark.asyncio
async def test_handoff_starts_finalization_once_while_sip_call_continues() -> None:
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        status=CallSessionStatus.CONNECTED,
        handoff_state=HandoffState.COMPLETED,
    )

    class Session:
        finalization = None

        async def scalar(self, query):
            return self.finalization

        async def get(self, model, key):
            return call

        def add(self, value):
            if isinstance(value, CallFinalization):
                self.finalization = value

        def add_all(self, values):
            assert not list(values)

        async def flush(self):
            return None

    session = Session()
    commands = _Commands()
    service = FinalizationService(session, commands)  # type: ignore[arg-type]

    async def no_actions(call):
        return []

    async def no_schedule(finalization, causation_id):
        return None

    service._actions = no_actions  # type: ignore[method-assign]
    service._schedule = no_schedule  # type: ignore[method-assign]
    first = await service.start(
        call_event(call.id, call.tenant_id, "agent_relinquished")
    )
    assert call.status is CallSessionStatus.CONNECTED
    assert len(commands.sent) == 1

    call.status = CallSessionStatus.ENDED
    second = await service.start(call_event(call.id, call.tenant_id, "ended"))
    assert second is first
    assert len(commands.sent) == 1
