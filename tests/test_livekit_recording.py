import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.livekit_recording import (
    RecordingHandle,
    RecordingSettings,
    save_base64_file,
    start_room_recording,
    wait_for_recording,
)


class FakeEgress:
    def __init__(self, *, active=None, states=None):
        self.active = active or []
        self.states = list(states or [])
        self.state_index = 0
        self.started = []

    async def list_egress(self, _request):
        if self.active:
            return SimpleNamespace(items=self.active)
        if not self.states:
            return SimpleNamespace(items=[])
        state = self.states[min(self.state_index, len(self.states) - 1)]
        self.state_index += 1
        return SimpleNamespace(items=[state])

    async def start_room_composite_egress(self, request):
        self.started.append(request)
        return SimpleNamespace(egress_id="egress-1")


class FakeClient:
    def __init__(self, egress):
        self.egress = egress


def settings(tmp_path):
    return RecordingSettings(
        api_url="http://livekit:7880",
        api_key="key",
        api_secret="secret",
        output_dir=tmp_path,
        timeout_seconds=0.01,
        poll_seconds=0,
    )


def test_start_room_recording_is_audio_only_and_reuses_active_recording(tmp_path):
    egress = FakeEgress()
    handle = asyncio.run(
        start_room_recording(
            "voice-call-1", "call-1", client=FakeClient(egress), settings=settings(tmp_path)
        )
    )
    assert handle.egress_id == "egress-1"
    assert len(egress.started) == 1
    assert egress.started[0].audio_only is True
    assert egress.started[0].layout == ""
    assert egress.started[0].video_only is False
    assert egress.started[0].file_outputs[0].file_type == 2

    active = FakeEgress(active=[SimpleNamespace(egress_id="existing-egress")])
    reused = asyncio.run(
        start_room_recording(
            "voice-call-1", "call-1", client=FakeClient(active), settings=settings(tmp_path)
        )
    )
    assert reused.egress_id == "existing-egress"
    assert active.started == []


def test_wait_for_recording_requires_terminal_success_and_saves_base64_file(tmp_path):
    handle = RecordingHandle("egress-1", "voice-call-1", Path(tmp_path) / "call-1.ogg")
    handle.path.write_bytes(b"mixed guest and agent audio")
    egress = FakeEgress(states=[SimpleNamespace(status="EGRESS_COMPLETE", error="", details="")])
    asyncio.run(wait_for_recording(handle, client=FakeClient(egress), settings=settings(tmp_path)))
    delivery = save_base64_file(handle)
    assert Path(delivery["base64_file"]).read_text() == "bWl4ZWQgZ3Vlc3QgYW5kIGFnZW50IGF1ZGlv"
    assert delivery["content_type"] == "audio/ogg"


def test_wait_for_recording_times_out_without_falling_through(tmp_path):
    handle = RecordingHandle("egress-1", "voice-call-1", Path(tmp_path) / "call-1.ogg")
    egress = FakeEgress(states=[SimpleNamespace(status="EGRESS_ACTIVE")])
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(wait_for_recording(handle, client=FakeClient(egress), settings=settings(tmp_path)))
