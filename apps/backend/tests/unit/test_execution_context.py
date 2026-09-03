from backend_core.runtime.execution_context import _effective_runtime


def test_effective_runtime_preserves_snapshot_llm_and_execution_parameters() -> None:
    runtime = {
        "architecture": "cascade",
        "llm": {
            "parameters": {
                "deployment_ref": "deployment-id",
                "max_completion_tokens": 1024,
                "temperature": None,
                "reasoning_effort": None,
            },
            "resource": {
                "deployment": {"deployment_config": {"model": "gpt-5"}},
                "connection": {"provider_kind": "azure_openai"},
            },
        },
        "stt": {
            "speech_hints": {"keyterms": {"values": []}},
            "resource": {
                "deployment": {"deployment_config": {"model_id": "scribe"}},
                "connection": {"provider_kind": "elevenlabs"},
            },
        },
        "tts": {
            "defaults": {"min_sentence_chars": 20},
            "voice": "voice-default",
            "resource": {
                "deployment": {"deployment_config": {"model_id": "eleven"}},
                "connection": {"provider_kind": "elevenlabs"},
            },
        },
        "execution": {
            "policy": {
                "speech_activity": {
                    "min_speech_seconds": 0.05,
                    "min_silence_seconds": 0.25,
                    "activation_threshold": 0.5,
                },
                "stt_commit": {"strategy": "local_vad"},
                "endpointing": {
                    "min_delay_seconds": 0.1,
                    "max_delay_seconds": 0.7,
                },
                "interruption": {
                    "enabled": False,
                    "min_duration_seconds": 0.23,
                    "min_words": 4,
                    "false_interruption_timeout_seconds": 1.7,
                    "resume_after_false_interruption": False,
                },
                "response_scheduling": {
                    "preemptive_generation": False,
                    "preemptive_tts": False,
                },
            }
        },
    }

    result = _effective_runtime(runtime, "sk")

    assert result is not None
    assert result.llm.model == "gpt-5"
    assert result.llm.max_completion_tokens == 1024
    assert result.interruption.enabled is False
    assert result.response_scheduling.preemptive_generation is False
