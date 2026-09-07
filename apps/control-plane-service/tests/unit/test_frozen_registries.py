from dataclasses import fields, replace
from datetime import UTC, datetime
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from control_plane.application.components import ComponentService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)

FROZEN_SCOPES = {
    "SystemPrompt": {"platform"},
    "ProfilePrompt": {"profile"},
    "InteractionPrompt": {"interaction_mode"},
    "STTDefaults": {"system"},
    "LLMDefaults": {"system"},
    "TTSDefaults": {"system"},
    "RealtimeDefaults": {"system"},
    "Policies": {"system"},
    "TenantPrompt": {"tenant"},
    "Knowledge": {"tenant"},
    "AgentPersonality": {"tenant"},
    "BusinessInfo": {"tenant"},
    "ActionsDefinition": {"tenant"},
    "Architecture": {"tenant"},
    "ProfileReference": {"tenant"},
    "RuntimeOverrides": {"tenant"},
    "ActionsAvailability": {"tenant"},
}


def registry():
    from control_plane.domain.frozen_components import (
        default_component_definition_registry,
    )

    return default_component_definition_registry()


def address(kind: str):
    from control_plane.domain.components import InteractionModeScope, SystemScope

    scope = {
        "SystemPrompt": PlatformScope(),
        "ProfilePrompt": ProfileScope("hotel"),
        "InteractionPrompt": InteractionModeScope("voice"),
        "STTDefaults": SystemScope(),
        "LLMDefaults": SystemScope(),
        "TTSDefaults": SystemScope(),
        "RealtimeDefaults": SystemScope(),
        "Policies": SystemScope(),
    }.get(kind, TenantScope("tenant-a"))
    return ComponentAddress(ComponentKind(kind), scope)


def test_frozen_component_inventory_scope_and_schema_ownership() -> None:
    component_registry = registry()

    assert {str(item.kind) for item in component_registry.definitions} == set(
        FROZEN_SCOPES
    )
    for kind, scopes in FROZEN_SCOPES.items():
        definition = component_registry.resolve(address(kind))
        assert definition.schema_version == 1
        assert {scope.value for scope in definition.allowed_scopes} == scopes
        assert definition.value_schema["additionalProperties"] is False
        assert definition.metadata["lifecycle"] in {"versioned", "live"}


def test_component_registry_projection_contains_only_frozen_read_only_metadata() -> (
    None
):
    entry = registry().entries[0]
    assert {item.name for item in fields(entry)} == {
        "key",
        "schema_version",
        "allowed_scopes",
        "value_schema",
        "metadata",
    }
    assert entry.allowed_scopes == ("platform",)
    with pytest.raises(TypeError):
        entry.metadata["operator_edit"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("kind", "invalid_scope_name"),
    [
        ("SystemPrompt", "system"),
        ("ProfilePrompt", "platform"),
        ("InteractionPrompt", "profile"),
        ("Architecture", "system"),
        ("STTDefaults", "tenant"),
    ],
)
def test_frozen_component_scopes_reject_every_other_scope(
    kind: str, invalid_scope_name: str
) -> None:
    from control_plane.domain.components import SystemScope

    invalid_scope = {
        "system": SystemScope(),
        "platform": PlatformScope(),
        "profile": ProfileScope("hotel"),
        "tenant": TenantScope("tenant-a"),
    }[invalid_scope_name]
    with pytest.raises(ScopeNotAllowed):
        registry().resolve(
            ComponentAddress(ComponentKind(kind), invalid_scope)  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("SystemPrompt", {"content": "system"}),
        ("ProfilePrompt", {"content": "profile"}),
        ("InteractionPrompt", {"content": "voice"}),
        ("STTDefaults", {"deployment_ref": "00000000-0000-0000-0000-000000000001"}),
        (
            "LLMDefaults",
            {
                "deployment_ref": "00000000-0000-0000-0000-000000000001",
                "temperature": None,
                "reasoning_effort": None,
                "max_completion_tokens": 1,
            },
        ),
        (
            "TTSDefaults",
            {
                "deployment_ref": "00000000-0000-0000-0000-000000000001",
                "default_voice_id": "marin",
            },
        ),
        (
            "RealtimeDefaults",
            {
                "deployment_ref": "00000000-0000-0000-0000-000000000001",
                "input_transcription": {
                    "deployment_ref": "00000000-0000-0000-0000-000000000002"
                },
                "default_voice": "marin",
                "turn_completion": {"strategy": "semantic_vad", "eagerness": "auto"},
                "interruption": {"enabled": True},
            },
        ),
        (
            "Policies",
            {
                "cascade": {
                    "speech_activity": {
                        "min_speech_seconds": 0.1,
                        "min_silence_seconds": 0.2,
                        "activation_threshold": 0.5,
                    },
                    "stt_commit": {"strategy": "local_vad"},
                    "endpointing": {
                        "min_delay_seconds": 0.1,
                        "max_delay_seconds": 0.2,
                    },
                    "interruption": {
                        "enabled": True,
                        "min_duration_seconds": 0,
                        "min_words": 0,
                        "false_interruption_timeout_seconds": 0,
                        "resume_after_false_interruption": True,
                    },
                    "response_scheduling": {
                        "preemptive_generation": False,
                        "preemptive_tts": False,
                    },
                    "tokenizer": {"min_sentence_chars": 3},
                }
            },
        ),
        ("TenantPrompt", {"content": "tenant"}),
        ("Knowledge", {"content": ""}),
        (
            "AgentPersonality",
            {
                "identity": "front_desk",
                "display_name": "Amelia",
                "greeting": "Hello",
                "conversation_scope": "property_only",
            },
        ),
        (
            "BusinessInfo",
            {
                "business": {"name": "Hotel", "type": "hotel"},
                "contact": {
                    "address": None,
                    "phones": [],
                    "emails": ["hello@example.com"],
                    "website": None,
                },
                "localization": {
                    "default_locale": "en-US",
                    "timezone": "Europe/Bucharest",
                },
            },
        ),
        (
            "ActionsDefinition",
            {
                "actions": {
                    "lookup": {
                        "phase": "runtime",
                        "description": "Look up a booking",
                        "announcement": "One moment",
                        "agent_input_schema": {},
                        "execution": {
                            "integration_key": "pms",
                            "method": "GET",
                            "timeout_seconds": 1,
                            "request": {"codec": "none"},
                            "response": {"codec": "none"},
                        },
                    }
                }
            },
        ),
        ("Architecture", {"architecture_key": "cascade"}),
        ("ProfileReference", {"profile_key": "hotel"}),
        ("RuntimeOverrides", {"stt": {"keyterms": []}}),
        ("ActionsAvailability", {"actions": {"lookup": True}}),
    ],
)
def test_each_frozen_component_accepts_its_minimal_structural_value(
    kind: str, value: object
) -> None:
    registry().resolve(address(kind)).deserialize(value)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("SystemPrompt", {}),
        ("SystemPrompt", {"content": "ok", "unknown": True}),
        ("SystemPrompt", {"content": None}),
        (
            "LLMDefaults",
            {
                "deployment_ref": "00000000-0000-0000-0000-000000000001",
                "max_completion_tokens": 0,
            },
        ),
        (
            "LLMDefaults",
            {
                "deployment_ref": "00000000-0000-0000-0000-000000000001",
                "temperature": 2.01,
                "max_completion_tokens": 1,
            },
        ),
        (
            "AgentPersonality",
            {
                "identity": "FrontDesk",
                "display_name": "Amelia",
                "greeting": "Hello",
                "conversation_scope": "property_only",
            },
        ),
        (
            "BusinessInfo",
            {
                "business": {"name": "Hotel", "type": "hotel"},
                "contact": {"phones": [], "emails": ["not-an-email"]},
                "localization": {"default_locale": "en_us", "timezone": "UTC"},
            },
        ),
        ("RuntimeOverrides", {"llm": {"temperature": 1}}),
        ("RuntimeOverrides", {"tts": None}),
        ("RuntimeOverrides", {"stt": {"keyterms": None}}),
    ],
)
def test_frozen_structural_boundaries_reject_invalid_values(
    kind: str, value: object
) -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(address(kind)).deserialize(value)


def test_code_owned_registries_resolve_frozen_keys_and_are_read_only() -> None:
    from control_plane.domain.registries import (
        ArchitectureRegistry,
        DeploymentKindRegistry,
        IncompatibleRegistryReference,
        IntegrationKindRegistry,
        ProviderKindRegistry,
        UnknownRegistryKey,
    )

    registries_and_keys = (
        (ArchitectureRegistry(), ("cascade", "realtime", "half-cascade")),
        (ProviderKindRegistry(), ("azure_openai", "elevenlabs", "deepgram")),
        (DeploymentKindRegistry(), ("llm", "realtime", "stt", "tts")),
        (IntegrationKindRegistry(), ("http", "pms", "webhook")),
    )
    for kind_registry, keys in registries_and_keys:
        assert tuple(entry.key for entry in kind_registry.entries) == keys
        assert all(kind_registry.resolve(key).key == key for key in keys)
        assert not hasattr(kind_registry, "register")
        with pytest.raises(UnknownRegistryKey):
            kind_registry.resolve("unknown")
        with pytest.raises(TypeError):
            kind_registry.entries[0].metadata["operator_edit"] = True  # type: ignore[index]

    assert ProviderKindRegistry().resolve_for_deployment("azure_openai", "llm")
    with pytest.raises(IncompatibleRegistryReference):
        ProviderKindRegistry().resolve_for_deployment("azure_openai", "tts")

    component_registry = registry()
    with pytest.raises(RuntimeError, match="read-only"):
        component_registry.register(
            replace(
                component_registry.definitions[0],
                kind=ComponentKind("OperatorDefined"),
            )
        )


@pytest.mark.asyncio
async def test_component_service_uses_definition_schema_version() -> None:
    assert "schema_version" not in signature(ComponentService.save_draft).parameters
    repository = AsyncMock()
    repository.save_draft.return_value = SimpleNamespace(
        schema_version=1,
        value={"content": "hello"},
        version=1,
        based_on_revision_id=None,
        updated_at=datetime.now(UTC),
        updated_by="operator",
    )
    service = ComponentService(registry(), repository)

    await service.save_draft(
        address("SystemPrompt"), {"content": "hello"}, None, None, "operator"
    )

    assert repository.save_draft.await_args.args[2] == 1
    assert repository.save_draft.await_args.args[2] != 99
    assert repository.save_draft.await_args.args[0].kind == ComponentKind(
        "SystemPrompt"
    )
