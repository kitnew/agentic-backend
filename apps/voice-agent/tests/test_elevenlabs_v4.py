import pytest
from livekit.plugins.elevenlabs import tts as elevenlabs_tts

from voice_agent.providers import _create_tts


@pytest.mark.parametrize("model", ["eleven_v4", "eleven_v4_turbo"])
def test_elevenlabs_v4_models_use_dialogue_api(model: str) -> None:
    tts = _create_tts(
        {"deployment_config": {"model_id": model}, "voice": "voice-id"},
        "sk",
        "eleven-key",
    )

    assert tts._opts.model == model
    assert elevenlabs_tts.is_dialogue_model(tts._opts.model)
