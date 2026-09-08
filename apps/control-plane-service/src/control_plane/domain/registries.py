from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from contracts.integration import HttpConnectionConfiguration
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import DeploymentKind


class UnknownRegistryKey(ValueError):
    pass


class IncompatibleRegistryReference(ValueError):
    pass


class _ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AzureOpenAIConnectionConfig(_ProviderConfig):
    endpoint: AnyHttpUrl
    api_version: str | None = Field(default=None, min_length=1)


class _EmptyConnectionConfig(_ProviderConfig):
    pass


class _AzureOpenAILLMDeploymentConfig(_ProviderConfig):
    deployment_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_version: str = Field(min_length=1)


class _AzureOpenAIDeploymentConfig(_ProviderConfig):
    deployment_name: str = Field(min_length=1)


class _ModelDeploymentConfig(_ProviderConfig):
    model_id: str = Field(min_length=1)


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

    CASCADE = "cascade"
    REALTIME = "realtime"
    HALF_CASCADE = "half-cascade"

    entries = (
        RegistryEntry(
            CASCADE,
            "Cascade",
            "Cascaded STT, LLM, and TTS runtime",
            {"runtime_supported": True},
        ),
        RegistryEntry(
            REALTIME,
            "Realtime",
            "Realtime speech-to-speech runtime",
            {"runtime_supported": True},
        ),
        RegistryEntry(
            HALF_CASCADE,
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

    _connection_schemas: Mapping[str, type[_ProviderConfig]] = MappingProxyType(
        {
            "azure_openai": _AzureOpenAIConnectionConfig,
            "elevenlabs": _EmptyConnectionConfig,
            "deepgram": _EmptyConnectionConfig,
        }
    )
    _deployment_schemas: Mapping[tuple[str, DeploymentKind], type[_ProviderConfig]] = (
        MappingProxyType(
            {
                ("azure_openai", DeploymentKind.LLM): _AzureOpenAILLMDeploymentConfig,
                ("azure_openai", DeploymentKind.REALTIME): _AzureOpenAIDeploymentConfig,
                ("azure_openai", DeploymentKind.STT): _AzureOpenAIDeploymentConfig,
                ("elevenlabs", DeploymentKind.STT): _ModelDeploymentConfig,
                ("elevenlabs", DeploymentKind.TTS): _ModelDeploymentConfig,
                ("deepgram", DeploymentKind.STT): _ModelDeploymentConfig,
            }
        )
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

    def validate_connection(
        self, provider_kind: str, value: object
    ) -> dict[str, object]:
        try:
            self.resolve(provider_kind)
        except UnknownRegistryKey as error:
            raise InvalidManagedResource(str(error)) from error
        return self._validate(self._connection_schemas[provider_kind], value)

    def validate_deployment(
        self, provider_kind: str, deployment_kind: DeploymentKind, value: object
    ) -> dict[str, object]:
        try:
            self.resolve_for_deployment(provider_kind, deployment_kind.value)
            schema = self._deployment_schemas[(provider_kind, deployment_kind)]
        except (UnknownRegistryKey, IncompatibleRegistryReference, KeyError) as error:
            raise InvalidManagedResource(str(error)) from error
        return self._validate(schema, value)

    @staticmethod
    def _validate(schema: type[_ProviderConfig], value: object) -> dict[str, object]:
        try:
            return schema.model_validate(value).model_dump(mode="json")
        except ValidationError as error:
            raise InvalidManagedResource(str(error)) from error


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
    )
    _config_schemas: Mapping[str, type[BaseModel]] = MappingProxyType(
        {
            "http": HttpConnectionConfiguration,
        }
    )

    def resolve(self, key: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise UnknownRegistryKey(f"unknown integration kind: {key}")

    def validate_config(
        self, integration_kind: str, value: object
    ) -> dict[str, object]:
        try:
            self.resolve(integration_kind)
            schema = self._config_schemas[integration_kind]
            return schema.model_validate(value).model_dump(mode="json")
        except (UnknownRegistryKey, KeyError, ValidationError) as error:
            raise InvalidManagedResource(str(error)) from error
