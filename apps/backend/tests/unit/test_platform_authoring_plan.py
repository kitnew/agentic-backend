from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.tenants import platform_component_router as router
from contracts.authoring import AuthoringPlan
from contracts.voice_runtime import PlatformRuntimePolicy
from pydantic import ValidationError


def policy() -> PlatformRuntimePolicy:
    return PlatformRuntimePolicy.model_validate(
        {
            "llm": {"provider": "azure_openai", "model": "gpt-5.6-terra", "reasoning_effort": "none"},
            "stt": {
                "provider": "elevenlabs",
                "model": "scribe",
                "server_vad": {
                    "silence_threshold_seconds": 1,
                    "activity_threshold": 0.5,
                    "min_speech_ms": 100,
                    "min_silence_ms": 200,
                },
            },
            "tts": {"provider": "elevenlabs", "model": "turbo", "voice_id": "voice"},
            "local_vad": {
                "min_speech_seconds": 0.2,
                "min_silence_seconds": 0.4,
                "activation_threshold": 0.5,
            },
            "turn": {
                "detection": "stt",
                "min_endpointing_delay_seconds": 0.2,
                "max_endpointing_delay_seconds": 1,
            },
        }
    )


class ReadOnlyPlatformRepository:
    def __init__(self) -> None:
        self.writes = 0
        self.runtime = SimpleNamespace(payload=policy().model_dump(mode="json"))
        self.system = SimpleNamespace(text="old system")
        self.profiles = [SimpleNamespace(profile="hotel_assistant", text="old profile")]

    async def runtime_draft(self):
        return self.runtime

    async def system_prompt_draft(self):
        return self.system

    async def profile_drafts(self):
        return self.profiles


@pytest.mark.asyncio
async def test_platform_plan_endpoints_use_read_only_state_and_return_authoring_plan(monkeypatch):
    repository = ReadOnlyPlatformRepository()
    monkeypatch.setattr(router, "PlatformReleaseRepository", lambda session: repository)

    runtime = await router.plan_runtime(
        router.RuntimeDraftWrite(policy=policy()), object()
    )
    system = await router.plan_system_prompt(
        router.PromptDraftWrite(text="new system"), object()
    )
    profile = await router.plan_profile_prompt(
        "hotel_assistant", router.PromptDraftWrite(text="new profile"), object()
    )

    assert all(isinstance(item, AuthoringPlan) and item.valid for item in (runtime, system, profile))
    assert repository.writes == 0
    assert runtime.impact.affected_components == ["runtime"]
    assert system.impact.affected_components == ["system_prompt"]
    assert profile.impact.affected_components == ["profile_prompt:hotel_assistant"]


@pytest.mark.parametrize(
    "model, value",
    [
        (router.RuntimeDraftWrite, {"policy": {"llm": {}}}),
        (router.PromptDraftWrite, {"text": ""}),
    ],
)
def test_platform_plan_and_save_share_typed_validation(model, value):
    with pytest.raises(ValidationError) as plan_error:
        model.model_validate(value)
    with pytest.raises(ValidationError) as save_error:
        model.model_validate(value)
    assert str(plan_error.value) == str(save_error.value)


def test_platform_publish_response_accepts_uuid_identifiers() -> None:
    response = router.PlatformReleaseResponse.model_validate(
        SimpleNamespace(
            id=uuid4(),
            release_number=1,
            runtime_revision_id=uuid4(),
            system_prompt_revision_id=uuid4(),
        ),
        from_attributes=True,
    )
    assert response.release_number == 1
