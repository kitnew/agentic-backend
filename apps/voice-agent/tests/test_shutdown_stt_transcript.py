import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import Agent, llm, stt
from livekit.agents.language import LanguageCode
from livekit.agents.voice.agent_activity import AgentActivity
from livekit.agents.voice.audio_recognition import AudioRecognition
from voice_agent.event_delivery import ConversationPersistence
from voice_agent.observability import LatencyInstrumentedAgent
from voice_agent.recent_transcript import RecentTranscriptBuffer
from voice_agent.stt_role import role_for_architecture


@pytest.mark.parametrize("architecture", ["realtime", "half-cascade"])
@pytest.mark.asyncio
async def test_shutdown_does_not_persist_the_stt_accumulator_as_a_new_turn(
    architecture: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Backend:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def append_conversation_message(self, call_id, payload) -> None:
            self.messages.append(payload.content)

    backend = Backend()
    persistence = ConversationPersistence(backend, uuid4())  # type: ignore[arg-type]
    for item_id, text in (("provider-a", "A"), ("provider-b", "B"), ("provider-c", "C")):
        persistence.on_conversation_item_added(
            SimpleNamespace(item=llm.ChatMessage(id=item_id, role="user", content=[text]))
        )

    source_events = [
        stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language=LanguageCode("sk"), text=text)],
        )
        for text in ("A", "B", "C")
    ]

    async def standalone_stt(*_args: object):
        for event in source_events:
            yield event

    monkeypatch.setattr(Agent.default, "stt_node", staticmethod(standalone_stt))
    recent_transcript = RecentTranscriptBuffer()
    agent = LatencyInstrumentedAgent(
        metrics=None,
        recent_transcript=recent_transcript,
        standalone_stt_role=role_for_architecture(architecture),
        instructions="test",
    )

    activity = SimpleNamespace(
        _session=SimpleNamespace(
            _amd=None,
            _closing=True,
            _conversation_item_added=lambda message: persistence.on_conversation_item_added(
                SimpleNamespace(item=message)
            ),
        ),
        _agent=SimpleNamespace(_chat_ctx=SimpleNamespace(items=[])),
        _scheduling_paused=True,
        _new_turns_blocked=False,
        _cancel_preemptive_generation=lambda: None,
        _init_metrics_from_end_of_turn=lambda info: None,
    )
    recognition = object.__new__(AudioRecognition)
    for name, value in {
        "_vad": None,
        "_last_speaking_time": None,
        "_turn_detection_mode": "realtime_llm",
        "_last_language": None,
        "_final_transcript_received": asyncio.Event(),
        "_hooks": SimpleNamespace(
            on_final_transcript=lambda *args, **kwargs: None,
            retrieve_chat_ctx=lambda: llm.ChatContext(),
        ),
        "_session": SimpleNamespace(amd=None),
        "_last_final_transcript_time": None,
        "_audio_transcript": "",
        "_audio_preflight_transcript": "",
        "_audio_interim_transcript": "",
        "_final_transcript_confidence": [],
        "_user_turn_committed": False,
        "_vad_base_turn_detection": False,
        "_user_silence_ev": asyncio.Event(),
        "_check_user_turn_limit": lambda transcript: None,
        "_stt": object(),
        "_closing": asyncio.Event(),
        "_commit_user_turn_atask": None,
    }.items():
        setattr(recognition, name, value)

    def commit_eou(chat_ctx, *, trigger, skip_reply=False) -> None:
        if recognition._stt and not recognition._audio_transcript:
            return
        info = SimpleNamespace(
            new_transcript=recognition._audio_transcript,
            transcript_confidence=0,
            metrics=None,
            backchannel_over_agent=False,
            user_turn_span=None,
        )
        AgentActivity.on_end_of_turn(activity, info)

    recognition._run_eou_detection = commit_eou
    forwarded = [event async for event in agent.stt_node(None, None)]  # type: ignore[arg-type]
    for event in forwarded:
        recognition._process_stt_event(event)
    recognition._last_final_transcript_time = time.time()

    await recognition._commit_user_turn(audio_detached=True, transcript_timeout=0)
    assert await persistence.finish()

    assert forwarded == []
    assert recent_transcript.recent(10)["combined_text"] == "A B C"
    assert backend.messages == ["A", "B", "C"]
