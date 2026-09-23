from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import llm
from voice_agent.event_delivery import (
    ConversationPersistence,
)
from voice_agent.recent_transcript import RecentTranscriptBuffer


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
async def test_persistence_writes_only_realtime_conversation_items() -> None:
    class Backend:
        def __init__(self) -> None:
            self.messages = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append(payload)

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]
    precision = RecentTranscriptBuffer()
    precision.on_stt_final("Dobrý den")
    persistence.on_conversation_item_added(event("realtime-user", "Dobrý deň"))
    persistence.on_conversation_item_added(event("reply", "Vitajte", "assistant"))

    assert await persistence.finish()
    assert [(item.role.value, item.content) for item in backend.messages] == [
        ("user", "Dobrý deň"),
        ("assistant", "Vitajte"),
    ]
    assert precision.recent(1)["combined_text"] == "Dobrý den"


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
