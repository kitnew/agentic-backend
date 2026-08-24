from uuid import uuid4

import pytest
from backend_core.runtime.finalization.models import (
    CallFinalization,
    FinalizationStatus,
    PostCallActionExecution,
    WorkStatus,
)
from backend_core.runtime.finalization.service import FinalizationService
from contracts import RuntimeHttpExecution, RuntimePostCallAction


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
        execution = RuntimeHttpExecution(connection_id=uuid4(), method="POST", timeout_seconds=5)
        return [
            RuntimePostCallAction(action_id="first", execution=execution),
            RuntimePostCallAction(action_id="second", execution=execution),
        ]

    await service._schedule(finalization, uuid4())

    assert len(commands.sent) == 1
    assert commands.sent[0].payload["action_id"] == "second"
    assert finalization.status is FinalizationStatus.PROCESSING
