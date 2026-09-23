from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents.voice.events import UserInputTranscribedEvent
from test_voice_agent import runtime_context
from voice_agent.main import build_agent_tools
from voice_agent.recent_transcript import RecentTranscriptBuffer, recent_transcript_tool


def event(text: str, *, final: bool = True) -> UserInputTranscribedEvent:
    return UserInputTranscribedEvent(transcript=text, is_final=final)


def test_buffer_accepts_only_finalized_stt_events_and_retains_recent_segments() -> None:
    buffer = RecentTranscriptBuffer(max_segments=2)
    buffer.on_user_input_transcribed(event("draft", final=False))
    buffer.on_user_input_transcribed(event("one"))
    buffer.on_user_input_transcribed(event("two"))
    buffer.on_user_input_transcribed(event("three"))

    assert buffer.recent(10) == {
        "segments": [{"seq": 2, "text": "two"}, {"seq": 3, "text": "three"}],
        "combined_text": "two three",
    }


@pytest.mark.asyncio
async def test_tool_returns_one_or_multiple_recent_segments() -> None:
    buffer = RecentTranscriptBuffer()
    recorded: list[dict[str, object]] = []
    for text in ("one", "two", "three"):
        buffer.on_user_input_transcribed(event(text))
    tool = recent_transcript_tool(buffer, lambda **values: recorded.append(values))
    context = SimpleNamespace()
    turns_schema = tool._info.raw_schema["parameters"]["properties"]["turns"]  # type: ignore[attr-defined]
    assert turns_schema["minimum"] == 1
    assert turns_schema["maximum"] == 10

    assert await tool._func(context, {"turns": 1}) == {  # type: ignore[attr-defined]
        "segments": [{"seq": 3, "text": "three"}],
        "combined_text": "three",
    }
    assert await tool._func(context, {"turns": 2}) == {  # type: ignore[attr-defined]
        "segments": [{"seq": 2, "text": "two"}, {"seq": 3, "text": "three"}],
        "combined_text": "two three",
    }
    assert [item["name"] for item in recorded] == [
        "get_recent_transcript",
        "get_recent_transcript",
    ]
    assert [item["status"] for item in recorded] == ["ok", "ok"]


@pytest.mark.asyncio
async def test_multi_turn_spelling_and_buffer_isolation() -> None:
    first = RecentTranscriptBuffer()
    second = RecentTranscriptBuffer()
    for text in ("F", "R I", "E S E", "N"):
        first.on_user_input_transcribed(event(text))
    second.on_user_input_transcribed(event("other call"))

    tool = recent_transcript_tool(first)
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(), {"turns": 4}
    )
    assert result["combined_text"] == "F R I E S E N"
    assert second.recent(1) == {
        "segments": [{"seq": 1, "text": "other call"}],
        "combined_text": "other call",
    }


@pytest.mark.parametrize("architecture", ["realtime", "half-cascade"])
def test_realtime_architectures_expose_recent_transcript_tool(
    architecture: str,
) -> None:
    context = runtime_context().model_copy(update={"architecture": architecture})
    tools = build_agent_tools(
        context,
        None,  # type: ignore[arg-type]
        uuid4(),
        recent_transcript=RecentTranscriptBuffer(),
    )

    names = [
        tool._info.name if hasattr(tool, "_info") else tool.id  # type: ignore[attr-defined]
        for tool in tools
    ]
    assert "get_recent_transcript" in names
