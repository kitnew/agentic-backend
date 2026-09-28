import asyncio
import json

from benchmarks.pipeline.cascade.llm_to_tts_latency import (
    ImmediateTokenizer,
    ObservedSentenceTokenizer,
    redact_error,
    replay,
    report,
    stages,
)


def test_monotonic_stages_and_unavailable():
    result = stages({"provider_text": 10, "livekit_text": 20, "tokenizer_emit": 30})
    assert result["provider_to_livekit_ms"] == 10 / 1e6
    assert result["livekit_to_tokenizer_ms"] == 10 / 1e6
    assert result["websocket_to_provider_audio_ms"] is None
    assert result["tokenizer_to_tts_receive_ms"] is None


def test_replay_and_empty_delta():
    async def run():
        seen = []
        await replay(
            [
                {"relative_ms": 0, "text": ""},
                {"relative_ms": 1, "text": "A"},
                {"relative_ms": 2, "text": "hoj."},
            ],
            seen.append,
        )
        assert seen == ["", "A", "hoj."]

    asyncio.run(run())


def test_tokenizer_capture_and_bypass():
    async def run():
        tokenizer = ObservedSentenceTokenizer(20)
        rec = {"ns": {}, "tokenizer_input": [], "tokenizer_output": []}
        tokenizer.rec = rec
        stream = tokenizer.stream()
        stream.push_text("Dobrý deň. Ďalšia veta.")
        stream.end_input()
        emitted = [token.token async for token in stream]
        assert emitted
        assert rec["tokenizer_input"][0]["text"] == "Dobrý deň. Ďalšia veta."
        assert rec["tokenizer_output"][0]["text"] == emitted[0]
        immediate = ImmediateTokenizer().stream()
        immediate.push_text("Dobrý deň.")
        immediate.end_input()
        assert [token.token async for token in immediate] == ["Dobrý deň."]

    asyncio.run(run())


def test_aggregation_unavailable_and_secret_redaction(tmp_path):
    secret = "sk-secret-example"
    assert secret not in json.dumps(redact_error(RuntimeError(secret)))
    row = {
        "kind": "CURRENT",
        "warmup": False,
        "status": "ok",
        "provider_to_livekit_ms": None,
        "llm_text_to_audio_ms": 100.0,
        "cadence": [],
        "tokenizer_output": [],
        "timestamps_ms": {},
    }
    report([row], {"model": "test"}, tmp_path)
    summary = json.loads((tmp_path / "llm_to_tts_latency.json").read_text())
    assert summary["successful_runs"] == 1
    assert summary["table"][0]["n"] == 0
    assert summary["table"][-1]["median_ms"] == 100.0
