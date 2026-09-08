from types import SimpleNamespace
from uuid import UUID

import pytest
from backend_core.runtime.execution_context import ExecutionContextReader
from contracts import VoiceExecutionContext


@pytest.mark.asyncio
async def test_voice_context_is_passed_through_without_snapshot_reconstruction() -> (
    None
):
    expected = VoiceExecutionContext(
        execution_id=UUID(int=1),
        tenant={"locale": "sk-SK", "timezone": "Europe/Bratislava"},
        agent={"name": "Agent", "personality": "default", "greeting": "Hello"},
        architecture="cascade",
        prompts={"system": "system", "profile": "", "tenant": "", "knowledge": ""},
        runtime={"stt": {}, "llm": {}, "tts": {}, "realtime": None},
        actions=[],
        handoff=[],
    )

    class Client:
        async def voice_context(self, execution_id):
            assert execution_id == expected.execution_id
            return expected

    result = await ExecutionContextReader(Client()).read(  # type: ignore[arg-type]
        SimpleNamespace(execution_id=expected.execution_id)  # type: ignore[arg-type]
    )

    assert result is expected
