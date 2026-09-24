import asyncio

import pytest

from benchmarks.pipeline.first_chunk import FirstChunkTTS


@pytest.mark.asyncio
async def test_first_chunk_starts_tts_before_model_stream_finishes():
    synthesized = []

    async def synthesize(text):
        synthesized.append(text)
        return {"status": "ok"}

    chunker = FirstChunkTTS(synthesize, min_sentence_chars=5)
    chunker.push("Dobrý deň. ", 0)
    await asyncio.sleep(0)
    chunker.push("Ako vám pomôžem?", 0)
    result = await chunker.finish()
    assert result["status"] == "ok"
    assert synthesized and synthesized[0].startswith("Dobrý")


@pytest.mark.asyncio
async def test_realtime_text_mode_feeds_half_cascade_tts():
    import json
    import time

    from benchmarks.realtime.run import trial

    class Socket:
        events = iter(
            [
                {"type": "session.updated"},
                {"type": "response.created", "response": {"id": "r1"}},
                {"type": "response.output_text.delta", "delta": "Dobrý deň."},
                {"type": "response.done", "response": {"status": "completed"}},
            ]
        )

        async def send(self, payload):
            assert json.loads(payload)["type"]

        async def recv(self):
            return json.dumps(next(self.events))

    chunks = []
    row, _ = await trial(
        Socket(),
        b"\0\0",
        "prompt",
        time.perf_counter_ns(),
        1,
        modality="text",
        on_text_delta=lambda text, _: chunks.append(text),
    )
    assert row["status"] == "ok"
    assert chunks == ["Dobrý deň."]
