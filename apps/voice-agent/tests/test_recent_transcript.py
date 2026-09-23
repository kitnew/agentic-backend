from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import Agent, stt
from test_voice_agent import runtime_context
from voice_agent.main import build_agent_tools
from voice_agent.observability import LatencyInstrumentedAgent
from voice_agent.recent_transcript import RecentTranscriptBuffer, recent_transcript_tool


def test_buffer_retains_recent_final_stt_segments() -> None:
    buffer = RecentTranscriptBuffer(max_segments=2)
    for text in ("one", "two", "three"):
        buffer.on_stt_final(text)

    assert buffer.recent(10) == {
        "segments": [{"seq": 2, "text": "two"}, {"seq": 3, "text": "three"}],
        "combined_text": "two three",
    }


@pytest.mark.asyncio
async def test_tool_returns_one_or_multiple_recent_segments() -> None:
    buffer = RecentTranscriptBuffer()
    recorded: list[dict[str, object]] = []
    for text in ("one", "two", "three"):
        buffer.on_stt_final(text)
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
        first.on_stt_final(text)
    second.on_stt_final("other call")

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


@pytest.mark.asyncio
async def test_standalone_stt_final_reaches_only_precision_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider_events(*_args: object):
        yield stt.SpeechEvent(
            type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="sk", text="draft")],
        )
        yield stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="sk", text="F R I E S E N")],
        )

    monkeypatch.setattr(Agent.default, "stt_node", staticmethod(provider_events))
    buffer = RecentTranscriptBuffer()
    agent = LatencyInstrumentedAgent(
        metrics=None, recent_transcript=buffer, instructions="test"
    )
    events = [event async for event in agent.stt_node(None, None)]  # type: ignore[arg-type]

    assert len(events) == 2
    assert buffer.recent(10)["combined_text"] == "F R I E S E N"
