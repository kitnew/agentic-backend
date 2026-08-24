from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from backend_core.modules.tenants.release_compiler import compile_runtime_bundle
from backend_core.modules.tenants.release_repository import (
    DraftExpectation,
    TenantComponent,
)
from backend_core.modules.tenants.release_service import (
    InitialConfigurationIncompleteError,
    ReleaseComponents,
    TenantReleaseUseCases,
)
from contracts.runtime_bundle import RuntimeBundlePayload, RuntimeBundleProvenance
from contracts.voice import VoiceAgentPrompt
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    LLMRuntimeSettings,
    LocalVADRuntimeSettings,
    STTRuntimeSettings,
    TTSRuntimeSettings,
    TurnRuntimeSettings,
)


@dataclass
class Draft:
    id: UUID
    version: int
    payload: dict[str, object]
    created_by: UUID | None = None
    comment: str | None = None


@dataclass
class Revision:
    id: UUID
    payload: dict[str, object]


class FakeRepository:
    def __init__(self, drafts: dict[TenantComponent, Draft]) -> None:
        self.drafts = drafts
        self.tenant = SimpleNamespace(active_release_id=None)
        self.deleted = False
        self.added: list[object] = []

    async def tenant_for_update(self, tenant_id: UUID):
        return self.tenant

    async def active_release(self, tenant_id: UUID):
        return None

    async def drafts_for_update(
        self, tenant_id: UUID, expectations, *, require_complete_snapshot: bool
    ):
        return self.drafts

    async def seal(self, tenant_id: UUID, drafts):
        return {
            component: Revision(uuid4(), draft.payload)
            for component, draft in drafts.items()
        }

    async def add_bundle(self, bundle):
        self.added.append(bundle)
        return bundle

    async def bundle_for_hash(self, tenant_id, content_hash):
        return None

    async def next_release_number(self, tenant_id: UUID):
        return 1

    async def add_release(self, release):
        release.id = uuid4()
        self.added.append(release)
        return release

    async def phone_claim_for_tenant(self, tenant_id: UUID):
        return None

    async def phone_claim(self, phone_number: str):
        return None

    async def provisioning_for_update(self, tenant_id: UUID):
        return None

    async def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.added.append(value)

    async def delete_drafts(self, drafts):
        self.deleted = True


def _runtime_payload() -> RuntimeBundlePayload:
    return RuntimeBundlePayload(
        voice_runtime=EffectiveVoiceRuntime(
            llm=LLMRuntimeSettings(
                provider="azure_openai", model="gpt-4.1", temperature=0.1
            ),
            stt=STTRuntimeSettings(
                provider="elevenlabs",
                model="scribe",
                server_vad={
                    "silence_threshold_seconds": 1,
                    "activity_threshold": 0.5,
                    "min_speech_ms": 100,
                    "min_silence_ms": 100,
                },
            ),
            tts=TTSRuntimeSettings(
                provider="elevenlabs", model="flash", voice_id="voice"
            ),
            turn=TurnRuntimeSettings(
                detection="stt",
                min_endpointing_delay_seconds=0.1,
                max_endpointing_delay_seconds=1,
            ),
            local_vad=LocalVADRuntimeSettings(
                min_speech_seconds=0.1,
                min_silence_seconds=0.1,
                activation_threshold=0.5,
            ),
            locale="en",
        ),
        locale="en",
        timezone="Europe/Bucharest",
        agent_display_name="Agent",
        greeting="Hello",
        conversation_scope="property_only",
        prompt=VoiceAgentPrompt(system_prompt="System"),
    )


def _drafts() -> dict[TenantComponent, Draft]:
    tenant_payloads = {
        TenantComponent.RUNTIME: {},
        TenantComponent.AGENT: {
            "business": {"name": "Test Hotel", "type": "hotel"},
            "contact": {},
            "localization": {
                "default_locale": "en",
                "timezone": "Europe/Bucharest",
            },
            "agent": {
                "display_name": "Agent",
                "greeting": "Hello",
                "profile": "hotel_assistant",
            },
            "conversation": {"scope": "property_only"},
            "handoff": {"destinations": {}},
        },
        TenantComponent.PROMPT: {"text": ""},
        TenantComponent.KNOWLEDGE: {},
        TenantComponent.CAPABILITIES: {"capabilities": {}},
        TenantComponent.POST_CALL: {"actions": []},
        TenantComponent.TELEPHONY: {
            "phone_number": None,
        },
    }
    return {
        component: Draft(uuid4(), 1, payload)
        for component, payload in tenant_payloads.items()
    }


def _bundle_factory(tenant_id: UUID):
    def build(components: ReleaseComponents):
        return compile_runtime_bundle(
            tenant_id=tenant_id,
            payload=_runtime_payload(),
            provenance=RuntimeBundleProvenance(
                runtime_revision_id=components.runtime.id,
                agent_revision_id=components.agent.id,
                prompt_revision_id=components.prompt.id,
                knowledge_revision_id=components.knowledge.id,
                capabilities_revision_id=components.capabilities.id,
                post_call_revision_id=components.post_call.id,
                telephony_revision_id=components.telephony.id,
                platform_runtime_revision_id=uuid4(),
                system_prompt_revision_id=uuid4(),
                profile_prompt_revision_id=uuid4(),
            ),
            compiler_build_id="test",
        )

    return build


@pytest.mark.asyncio
async def test_first_publish_all_requires_exact_six_draft_snapshot() -> None:
    tenant_id = uuid4()
    repository = FakeRepository(_drafts())
    use_cases = TenantReleaseUseCases(repository)  # type: ignore[arg-type]
    expected = [
        DraftExpectation(component, draft.id, draft.version)
        for component, draft in repository.drafts.items()
    ]

    release = await use_cases.publish(
        tenant_id,
        expected,
        _bundle_factory(tenant_id),
        publish_all=True,
    )

    assert release.release_number == 1
    assert repository.tenant.active_release_id == release.id
    assert repository.deleted


@pytest.mark.asyncio
async def test_first_publish_all_rejects_missing_component() -> None:
    tenant_id = uuid4()
    repository = FakeRepository(_drafts())
    use_cases = TenantReleaseUseCases(repository)  # type: ignore[arg-type]
    expected = [
        DraftExpectation(component, draft.id, draft.version)
        for component, draft in repository.drafts.items()
        if component is not TenantComponent.KNOWLEDGE
    ]

    with pytest.raises(InitialConfigurationIncompleteError) as caught:
        await use_cases.publish(
            tenant_id,
            expected,
            _bundle_factory(tenant_id),
            publish_all=True,
        )

    assert caught.value.missing == {TenantComponent.KNOWLEDGE}
