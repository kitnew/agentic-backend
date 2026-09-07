from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


class UnknownRegistryKey(ValueError):
    pass


class IncompatibleRegistryReference(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    key: str
    name: str
    description: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ArchitectureRegistry:
    __slots__ = ()

    entries = (
        RegistryEntry(
            "cascade",
            "Cascade",
            "Cascaded STT, LLM, and TTS runtime",
            {"runtime_supported": True},
        ),
        RegistryEntry(
            "realtime",
            "Realtime",
            "Realtime speech-to-speech runtime",
            {"runtime_supported": True},
        ),
        RegistryEntry(
            "half-cascade",
            "Half cascade",
            "Reserved half-cascade runtime",
            {"runtime_supported": False},
        ),
    )

    def resolve(self, key: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise UnknownRegistryKey(f"unknown architecture: {key}")


class ProviderKindRegistry:
    __slots__ = ()

    entries = (
        RegistryEntry(
            "azure_openai",
            "Azure OpenAI",
            "Azure OpenAI provider",
            {"deployment_kinds": ("llm", "realtime", "stt")},
        ),
        RegistryEntry(
            "elevenlabs",
            "ElevenLabs",
            "ElevenLabs speech provider",
            {"deployment_kinds": ("stt", "tts")},
        ),
        RegistryEntry(
            "deepgram",
            "Deepgram",
            "Deepgram speech provider",
            {"deployment_kinds": ("stt",)},
        ),
    )

    def resolve(self, key: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise UnknownRegistryKey(f"unknown provider kind: {key}")

    def resolve_for_deployment(
        self, provider_key: str, deployment_key: str
    ) -> RegistryEntry:
        entry = self.resolve(provider_key)
        deployment_kinds = entry.metadata["deployment_kinds"]
        assert isinstance(deployment_kinds, tuple)
        if deployment_key not in deployment_kinds:
            raise IncompatibleRegistryReference(
                f"provider {provider_key} does not support {deployment_key}"
            )
        return entry


class DeploymentKindRegistry:
    __slots__ = ()

    entries = tuple(
        RegistryEntry(key, name, f"{name} deployment", {"capability_kind": key})
        for key, name in (
            ("llm", "LLM"),
            ("realtime", "Realtime"),
            ("stt", "STT"),
            ("tts", "TTS"),
        )
    )

    def resolve(self, key: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise UnknownRegistryKey(f"unknown deployment kind: {key}")


class IntegrationKindRegistry:
    __slots__ = ()

    entries = (
        RegistryEntry(
            "http",
            "HTTP",
            "HTTP integration",
            {"config_schema": MappingProxyType({"type": "object"})},
        ),
        RegistryEntry(
            "pms",
            "PMS",
            "Property-management integration",
            {"config_schema": MappingProxyType({"type": "object"})},
        ),
        RegistryEntry(
            "webhook",
            "Webhook",
            "Webhook integration",
            {"config_schema": MappingProxyType({"type": "object"})},
        ),
    )

    def resolve(self, key: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise UnknownRegistryKey(f"unknown integration kind: {key}")
