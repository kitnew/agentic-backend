from backend_core.runtime.execution_context import _effective_runtime


def test_effective_runtime_ignores_snapshot_only_llm_parameters() -> None:
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
            }
        },
    }

    result = _effective_runtime(runtime, "sk")

    assert result is not None
    assert result.llm.model == "gpt-5"
