from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from livekit.agents import llm
from livekit.agents.voice.agent_activity import AgentActivity
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
            self.messages: list[Any] = []

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
async def test_provider_transcription_finals_reach_conversation_persistence() -> None:
    """Keep provider-owned Realtime transcription connected to persistence."""
    from livekit.agents.llm.realtime import InputTranscriptionCompleted

    class Backend:
        def __init__(self) -> None:
            self.messages: list[Any] = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append(payload)

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]

    class Session:
        _amd = None

        def _user_input_transcribed(self, event) -> None:
            pass

        def _conversation_item_added(self, message) -> None:
            persistence.on_conversation_item_added(SimpleNamespace(item=message))

    class ChatContext:
        def _upsert_item(self, message) -> None:
            pass

    activity = SimpleNamespace(
        _session=Session(),
        _agent=SimpleNamespace(_chat_ctx=ChatContext()),
        stt=object(),
    )
    for item_id, transcript, started_at in (
        ("provider-item-a", "A", 1.0),
        ("provider-item-b", "B", 2.0),
    ):
        AgentActivity._on_input_audio_transcription_completed(  # type: ignore[arg-type]
            activity,
            InputTranscriptionCompleted(
                item_id=item_id,
                transcript=transcript,
                is_final=True,
                turn_started_at=started_at,
            ),
        )

    assert await persistence.finish()
    assert [(message.role.value, message.content) for message in backend.messages] == [
        ("user", "A"),
        ("user", "B"),
    ]
    assert [message.source_created_at.timestamp() for message in backend.messages] == [
        1.0,
        2.0,
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
