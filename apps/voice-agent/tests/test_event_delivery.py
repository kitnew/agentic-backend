from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import llm
from livekit.agents.voice.events import UserInputTranscribedEvent
from voice_agent.event_delivery import (
    ConversationPersistence,
)


def event(item_id: str, content: str, role: str = "user") -> object:
    return SimpleNamespace(
        item=llm.ChatMessage(
            id=item_id,
            role=role,
            content=[content],
        )
    )


@pytest.mark.asyncio
async def test_persistence_writes_committed_items_in_queue_order() -> None:
    class Backend:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append(payload.content)

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]
    persistence.on_conversation_item_added(event("one", "first"))
    persistence.on_conversation_item_added(event("two", "second", "assistant"))
    persistence.on_conversation_item_added(event("handoff", "ignored", "system"))

    assert await persistence.finish()
    assert backend.messages == ["first", "second"]


@pytest.mark.asyncio
async def test_persistence_writes_final_standalone_stt_transcript() -> None:
    class Backend:
        def __init__(self) -> None:
            self.messages = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append(payload)

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]
    persistence.on_user_input_transcribed(
        UserInputTranscribedEvent(transcript="Dobrý deň", is_final=True)
    )
    persistence.on_user_input_transcribed(
        UserInputTranscribedEvent(transcript="Dobrý", is_final=False)
    )

    assert await persistence.finish()
    assert [(item.role.value, item.content) for item in backend.messages] == [
        ("user", "Dobrý deň")
    ]


@pytest.mark.asyncio
async def test_persistence_marks_incomplete_for_failed_items_only() -> None:
    class Backend:
        async def append_conversation_message(self, call_id, payload) -> None:
            raise RuntimeError("backend unavailable")

    persistence = ConversationPersistence(Backend(), uuid4())  # type: ignore[arg-type]
    persistence.on_conversation_item_added(event("one", "first"))
    persistence.on_conversation_item_added(event("system", "ignored", "system"))

    assert not await persistence.finish()
    assert persistence.incomplete
