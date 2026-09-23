from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.runtime.finalization.models import (
    CallFinalization,
    FinalizationStatus,
    PostCallActionExecution,
    WorkStatus,
)
from backend_core.runtime.finalization.service import FinalizationService
from contracts import ConversationMessageRole


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
                    role=ConversationMessageRole.USER, content="draft", interrupted=True
                ),
            ]

    service = FinalizationService(Session(), _Commands())  # type: ignore[arg-type]
    assert await service._transcript(uuid4()) == [
        {"role": "user", "message": "Dobrý deň"},
        {"role": "agent", "message": "Vitajte"},
    ]
