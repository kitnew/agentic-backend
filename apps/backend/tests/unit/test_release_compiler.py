from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
import yaml
from backend_core.modules.tenants.authoring import translate_capabilities
from backend_core.modules.tenants.release_compiler import (
    PlatformBundleInput,
    compile_runtime_bundle,
    compile_tenant_runtime_bundle,
)
from backend_core.runtime.capabilities.domain import CapabilityValidationError
from backend_core.runtime.capabilities.service import CapabilityInvocationService
from contracts import (
    CapabilityDateRangeConstraint,
    HttpExecution,
    TenantAgentConfig,
    TenantCapabilitiesConfig,
    TenantCapabilityProfile,
    TenantKnowledgeConfig,
    TenantPromptConfig,
    TenantRuntimeOverride,
    TenantTelephonyConfig,
)
from contracts.authoring import TenantCapabilitiesAuthoring
from contracts.runtime_bundle import (
    RuntimeBundlePayload,
    RuntimeBundleProvenance,
    RuntimeHttpExecution,
)
from contracts.tenant_components import TenantPostCallConfig
from contracts.voice import VoiceAgentPrompt
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    LLMRuntimeSettings,
    LocalVADRuntimeSettings,
    PlatformRuntimePolicy,
    STTRuntimeSettings,
    TTSRuntimeSettings,
    TurnRuntimeSettings,
)


def _payload() -> RuntimeBundlePayload:
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
        prompt=VoiceAgentPrompt(
            system_prompt="System", knowledge_base_revision_id=uuid4()
        ),
    )


def _provenance() -> RuntimeBundleProvenance:
    return RuntimeBundleProvenance(
        runtime_revision_id=uuid4(),
        agent_revision_id=uuid4(),
        prompt_revision_id=uuid4(),
        knowledge_revision_id=uuid4(),
        capabilities_revision_id=uuid4(),
        post_call_revision_id=uuid4(),
        telephony_revision_id=uuid4(),
        platform_runtime_revision_id=uuid4(),
        system_prompt_revision_id=uuid4(),
        profile_prompt_revision_id=uuid4(),
    )


def _platform() -> PlatformBundleInput:
    effective = _payload().voice_runtime
    return PlatformBundleInput(
        runtime_revision_id=uuid4(),
        system_prompt_revision_id=uuid4(),
        profile_prompt_revision_id=uuid4(),
        runtime_policy=PlatformRuntimePolicy.model_validate(
            effective.model_dump(exclude={"locale"})
        ),
        system_prompt="System",
        profile_prompt="Profile",
    )


def _compile_tenant(capabilities: TenantCapabilitiesConfig):
    return compile_tenant_runtime_bundle(
        tenant_id=uuid4(),
        runtime_revision_id=uuid4(),
        runtime=TenantRuntimeOverride(),
        agent_revision_id=uuid4(),
        agent=TenantAgentConfig.model_validate(
            {
                "business": {"name": "Hotel", "type": "hotel"},
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
            }
        ),
        prompt_revision_id=uuid4(),
        prompt=TenantPromptConfig(),
        knowledge_revision_id=uuid4(),
        knowledge=TenantKnowledgeConfig(),
        capabilities_revision_id=uuid4(),
        capabilities=capabilities,
        post_call_revision_id=uuid4(),
        post_call=TenantPostCallConfig(),
        telephony_revision_id=uuid4(),
        telephony=TenantTelephonyConfig(),
        platform=_platform(),
        compiler_build_id="test",
    )


def test_compiler_is_deterministic_without_release_identity() -> None:
    first = compile_runtime_bundle(
        tenant_id=uuid4(),
        payload=_payload(),
        provenance=_provenance(),
        compiler_build_id="test",
    )
    second = compile_runtime_bundle(
        tenant_id=first.bundle.tenant_id,
        payload=first.bundle.payload,
        provenance=first.bundle.provenance,
        compiler_build_id="test",
    )

    assert first.bundle.content_hash == second.bundle.content_hash
    assert first.bundle.id != second.bundle.id


def test_tenant_compiler_seals_arbitrary_capability_metadata() -> None:
    connection_id = uuid4()
    capability = TenantCapabilityProfile(
        enabled=True,
        semantic_version=1,
        description="Check an existing reservation",
        announcement="Checking now.",
        agent_input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["booked_name", "check_in", "check_out"],
            "properties": {
                "booked_name": {"type": "string"},
                "check_in": {"type": "string", "format": "date"},
                "check_out": {"type": "string", "format": "date"},
            },
        },
        bindings={
            "booked_name": "guest.name",
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
        },
        input_constraints=[
            CapabilityDateRangeConstraint(
                start="stay.check_in", end="stay.check_out", start_not_in_past=True
            )
        ],
        execution=HttpExecution(
            connection_id=connection_id,
            method="POST",
            request={
                "codec": "json",
                "mapping": {"guest_name": {"$expr": "business.guest.name"}},
            },
            response={"codec": "json", "mapping": None},
            timeout_seconds=10,
            result_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
        ),
    )
    compiled = _compile_tenant(
        capabilities=TenantCapabilitiesConfig(
            capabilities={"reservation.check_reservation": capability}
        )
    )

    definition = compiled.bundle.payload.capabilities[0]
    binding = compiled.bundle.payload.capability_bindings[0]
    assert definition.semantic_key == "reservation.check_reservation"
    assert definition.tool_name == binding.tool_name == "reservation_check_reservation"
    assert binding.input_schema == definition.input_schema
    assert binding.bindings == {
        "booked_name": "guest.name",
        "check_in": "stay.check_in",
        "check_out": "stay.check_out",
    }
    assert binding.input_constraints[0].start == "stay.check_in"
    assert binding.input_constraints[0].end == "stay.check_out"
    assert binding.input_constraints[0].start_not_in_past is True
    assert isinstance(binding.execution, RuntimeHttpExecution)
    assert binding.execution.connection_id == connection_id
    assert binding.execution.result_schema == capability.execution.result_schema
    assert (
        CapabilityInvocationService._requested_bundle_capability(
            [binding], "reservation.check_reservation"
        )
        is binding
    )
    assert (
        CapabilityInvocationService._requested_bundle_capability(
            [binding], "reservation_check_reservation"
        )
        is binding
    )


def test_tenant_compiler_rejects_duplicate_normalized_tool_names() -> None:
    capability = TenantCapabilityProfile(
        enabled=True,
        semantic_version=1,
        description="Check a reservation",
        announcement="Checking now.",
        agent_input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        execution=HttpExecution(connection_id=uuid4(), method="POST", timeout_seconds=10),
    )

    with pytest.raises(CapabilityValidationError, match="tenant_check_reservation") as error:
        _compile_tenant(
            TenantCapabilitiesConfig(
                capabilities={
                    "tenant.check_reservation": capability,
                    "tenant.check.reservation": capability,
                }
            )
        )

    assert error.value.code == "duplicate_tool_name"


@pytest.mark.asyncio
async def test_penzion_grand_capabilities_translate_and_compile() -> None:
    raw = yaml.safe_load(
        (
            Path(__file__).parents[4]
            / "definitions/tenants/penzion-grand/capabilities.yaml"
        ).read_text()
    )

    class Connections:
        async def get_by_key(self, tenant_id: UUID, key: str):
            return SimpleNamespace(id=uuid5(NAMESPACE_URL, key))

    translated = await translate_capabilities(
        TenantCapabilitiesAuthoring.model_validate(raw),
        tenant_id=uuid4(),
        connections=Connections(),
    )
    compiled = _compile_tenant(translated)

    assert len(compiled.bundle.payload.capability_bindings) == 5
    assert all(
        binding.input_constraints
        for binding in compiled.bundle.payload.capability_bindings
    )
