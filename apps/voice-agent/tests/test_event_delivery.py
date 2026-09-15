from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import llm
from voice_agent.event_delivery import (
    ConversationPersistence,
    message_from_user_input_event,
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
async def test_persistence_marks_incomplete_for_failed_items_only() -> None:
    class Backend:
        async def append_conversation_message(self, call_id, payload) -> None:
            raise RuntimeError("backend unavailable")

    persistence = ConversationPersistence(Backend(), uuid4())  # type: ignore[arg-type]
    persistence.on_conversation_item_added(event("one", "first"))
    persistence.on_conversation_item_added(event("system", "ignored", "system"))

    assert not await persistence.finish()
    assert persistence.incomplete


def test_user_input_transcript_creates_stable_user_message() -> None:
    call_id = uuid4()
    event = SimpleNamespace(
        transcript="hello",
        is_final=True,
        item_id="turn-1",
        created_at=100.0,
    )

    first = message_from_user_input_event(call_id, event)
    second = message_from_user_input_event(call_id, event)

    assert first is not None
    assert second is not None
    assert first.payload.message_id == second.payload.message_id
    assert first.payload.role.value == "user"
    assert first.payload.content == "hello"


@pytest.mark.asyncio
async def test_persistence_writes_final_external_user_transcript() -> None:
    class Backend:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append((payload.role.value, payload.content))

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]
    persistence.on_user_input_transcribed(
        SimpleNamespace(
            transcript="hello",
            is_final=False,
            item_id="turn-1",
            created_at=100.0,
        )
    )
    persistence.on_user_input_transcribed(
        SimpleNamespace(
            transcript="hello",
            is_final=True,
            item_id="turn-1",
            created_at=100.0,
        )
    )

    assert await persistence.finish()
    assert backend.messages == [("user", "hello")]
