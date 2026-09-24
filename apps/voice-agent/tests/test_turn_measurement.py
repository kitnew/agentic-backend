import json

from voice_agent.turn_measurement import TurnRecorder, causal_sum, derive


def test_derivation_keeps_missing_and_reverse_order_unavailable():
    values = derive(
        {
            "speech_end_proxy": 1_000_000,
            "eou": 2_000_000,
            "stt_final": 1_500_000,
            "output_boundary_proxy": 4_000_000,
        }
    )
    assert values["speech_to_eou"] == 1
    assert values["eou_to_stt_final"] is None
    assert values["speech_to_first_audio_output"] == 3
    assert values["llm_ttft"] is None
    assert causal_sum("cascade", values) is None


def test_causal_sum_uses_only_complete_nonoverlapping_stages():
    values = derive(
        {
            "speech_end_proxy": 0,
            "stt_final": 100_000_000,
            "eou": 200_000_000,
            "llm_start": 300_000_000,
            "llm_first_token": 400_000_000,
            "tts_input_first_text": 450_000_000,
            "first_speakable": 500_000_000,
            "tts_start": 500_000_000,
            "tts_first_audio": 600_000_000,
            "output_boundary_proxy": 700_000_000,
        }
    )
    assert causal_sum("cascade", values) == 700
    values["stt_final_to_eou"] = None
    assert causal_sum("cascade", values) is None


def test_realtime_and_half_cascade_causal_sums_ignore_sidecar_stt():
    realtime = derive(
        {
            "speech_end_proxy": 0,
            "response_created": 100_000_000,
            "realtime_first_audio": 300_000_000,
            "output_boundary_proxy": 400_000_000,
            "stt_final": 900_000_000,
        }
    )
    assert causal_sum("realtime", realtime) == 400
    half = derive(
        {
            "speech_end_proxy": 0,
            "response_created": 100_000_000,
            "tts_input_first_text": 200_000_000,
            "first_speakable": 250_000_000,
            "tts_start": 250_000_000,
            "tts_first_audio": 350_000_000,
            "output_boundary_proxy": 400_000_000,
            "stt_final": 900_000_000,
        }
    )
    assert causal_sum("half-cascade", half) == 400


def test_record_serialization_and_observer_classification(tmp_path):
    recorder = TurnRecorder(
        tmp_path,
        call_id="call-1",
        architecture="half-cascade",
        tenant_id="tenant-1",
        metadata={"stt": {"model": "scribe_v2_realtime"}},
    )
    recorder.start(speech_started=100)
    recorder.mark("speech_end_proxy", 200)
    recorder.mark("stt_final", 300)
    recorder.mark("response_created", 400)
    recorder.bind_speech("speech-1")
    recorder.mark_speech("speech-1", "first_speakable")
    recorder.output_started()
    recorder.complete_speech("speech-1")
    record = json.loads((tmp_path / "turns.jsonl").read_text())
    assert record["turn_id"]
    assert record["classification"]["stt_final"] == "observer"
    assert record["timestamps_ns"]["playout_enqueue"] is None
    assert record["latencies_ms"]["eou_to_stt_final"] is None
    assert "transcript" not in json.dumps(record)
    recorder.flush()
    assert len((tmp_path / "turns.jsonl").read_text().splitlines()) == 1


def test_cancelled_preemptive_speech_can_rebind_same_turn(tmp_path):
    recorder = TurnRecorder(
        tmp_path,
        call_id="call",
        architecture="cascade",
        tenant_id=None,
        metadata={},
    )
    recorder.start(speech_started=100)
    recorder.bind_speech("speculative")
    recorder.mark_speech("speculative", "llm_start", 200)
    recorder.complete_speech("speculative", interrupted=True)
    recorder.bind_speech("committed")
    recorder.mark_speech("committed", "llm_start", 300)
    recorder.output_started()
    recorder.complete_speech("committed")
    record = json.loads((tmp_path / "turns.jsonl").read_text())
    assert record["timestamps_ns"]["llm_start"] == 300
