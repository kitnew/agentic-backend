import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit import agents, rtc
from livekit.agents import llm
from test_voice_agent import FakeSpeechHandle, runtime_context, settings
from voice_agent.event_delivery import ConversationPersistence
from voice_agent.main import run_job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fraction", "close_error"),
    [(0, False), (0.2, False), (0.8, False), (1, False), (0.8, True)],
)
async def test_sip_disconnect_waits_for_last_playout_item_before_finalization(
    monkeypatch: pytest.MonkeyPatch, fraction: float, close_error: bool
) -> None:
    call_id = uuid4()
    events: list[str] = []
    recording_started = asyncio.Event()
    playout_finished = asyncio.Event()
    full_text = "Izba je dostupná na celé obdobie"
    played = full_text[: int(len(full_text) * fraction)]

    class Backend:
        async def runtime_context(self, call_id):
            return runtime_context()

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

        async def observe(self, call_id, observation_type, **kwargs):
            return None

        async def activate(self, call_id):
            return None

        async def start_recording(self, call_id):
            recording_started.set()

        async def append_conversation_message(self, call_id, payload):
            events.append(f"append:{payload.content}")
            assert payload.content == played
            assert payload.interrupted == (fraction < 1)

        async def complete(self, call_id, conversation_status):
            assert not close_error
            assert conversation_status == "complete"
            events.append("finalize")

        async def fail(self, call_id, reason, conversation_status):
            assert close_error
            assert reason == "provider_session_error"
            assert conversation_status == "incomplete"
            events.append("failed")

        async def aclose(self):
            return None

    class Persistence(ConversationPersistence):
        async def finish(self):
            result = await super().finish()
            events.append("finish")
            return result

    class Session:
        tts = None

        def __init__(self):
            self.callbacks: dict[str, list] = {}
            self.lock = asyncio.Lock()
            self.closed = False
            self.shutdowns = 0

        def on(self, event, callback):
            self.callbacks.setdefault(event, []).append(callback)

        def off(self, event, callback):
            self.callbacks[event].remove(callback)

        def emit(self, event, value):
            for callback in list(self.callbacks.get(event, [])):
                callback(value)

        async def start(self, agent, *, room, record):
            return None

        async def generate_reply(self, **kwargs):
            done = asyncio.get_running_loop().create_future()
            done.set_result(None)
            return FakeSpeechHandle(done)

        async def say(self, *args, **kwargs):
            return await self.generate_reply()

        def shutdown(self, *, drain):
            assert drain is False
            self.shutdowns += 1

        async def aclose(self):
            async with self.lock:
                if self.closed:
                    return
                await playout_finished.wait()
                if close_error:
                    raise RuntimeError("SDK teardown failed")
                if played:
                    events.append("item")
                    self.emit(
                        "conversation_item_added",
                        SimpleNamespace(
                            item=llm.ChatMessage(
                                id="last-playout",
                                role="assistant",
                                content=[played],
                                interrupted=fraction < 1,
                            )
                        ),
                    )
                self.closed = True
                self.emit(
                    "close",
                    SimpleNamespace(reason=agents.CloseReason.USER_INITIATED),
                )

    class Room:
        name = "sip-room"

        def __init__(self):
            self.callbacks = {}

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            self.callbacks.pop(event, None)

        def disconnect(self):
            self.callbacks["participant_disconnected"](
                SimpleNamespace(identity="caller")
            )

    class Job:
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')

        def __init__(self):
            self.room = Room()

        def add_shutdown_callback(self, callback):
            return None

        async def wait_for_participant(self, **kwargs):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                identity="caller",
                attributes={},
            )

    session = Session()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: Backend())
    monkeypatch.setattr("voice_agent.main.ConversationPersistence", Persistence)
    monkeypatch.setattr("voice_agent.main.create_agent_session", lambda *_: session)
    monkeypatch.setattr(
        "voice_agent.main.CallUsageReporter",
        lambda *args: SimpleNamespace(flush=lambda: asyncio.sleep(0)),
    )
    monkeypatch.setattr(
        "voice_agent.main.RingbackPlayer",
        lambda *args: SimpleNamespace(
            stop=lambda reason: None, aclose=lambda: asyncio.sleep(0)
        ),
    )

    job = Job()
    task = asyncio.create_task(run_job(job, settings()))
    await asyncio.wait_for(recording_started.wait(), 2)
    job.room.disconnect()
    job.room.disconnect()
    assert session.shutdowns == 1
    assert events == []
    playout_finished.set()
    await task
    assert events == (
        (["item", f"append:{played}"] if played and not close_error else [])
        + ["finish", "failed" if close_error else "finalize"]
    )
