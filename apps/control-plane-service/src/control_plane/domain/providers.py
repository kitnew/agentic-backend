from dataclasses import dataclass

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import DeploymentKind


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AzureOpenAIConnectionConfig(ProviderConfig):
    endpoint: AnyHttpUrl


class ElevenLabsConnectionConfig(ProviderConfig):
    pass


class AzureOpenAILLMDeploymentConfig(ProviderConfig):
    deployment_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_version: str = Field(min_length=1)


class AzureOpenAIRealtimeDeploymentConfig(ProviderConfig):
    deployment_name: str = Field(min_length=1)


class ElevenLabsSTTDeploymentConfig(ProviderConfig):
    model_id: str = Field(min_length=1)


class ElevenLabsTTSDeploymentConfig(ProviderConfig):
    model_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_kind: str
    connection_config: type[ProviderConfig]
    deployment_configs: dict[DeploymentKind, type[ProviderConfig]]

    def validate_connection(self, value: object) -> dict[str, object]:
        return self._validate(self.connection_config, value)

    def validate_deployment(
        self, kind: DeploymentKind, value: object
    ) -> dict[str, object]:
        model = self.deployment_configs.get(kind)
        if model is None:
            raise InvalidManagedResource(
                f"provider {self.provider_kind} does not support {kind.value}"
            )
        return self._validate(model, value)

    @staticmethod
    def _validate(model: type[ProviderConfig], value: object) -> dict[str, object]:
        try:
            return model.model_validate(value).model_dump(mode="json")
        except ValidationError as error:
            raise InvalidManagedResource(str(error)) from error


class ProviderRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ProviderDefinition] = {}

    def register(self, definition: ProviderDefinition) -> None:
        if definition.provider_kind in self._definitions:
            raise ValueError(f"duplicate provider: {definition.provider_kind}")
        self._definitions[definition.provider_kind] = definition

    def resolve(self, provider_kind: str) -> ProviderDefinition:
        try:
            return self._definitions[provider_kind]
        except KeyError as error:
            raise InvalidManagedResource(
                f"unknown provider: {provider_kind}"
            ) from error


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        ProviderDefinition(
            "azure_openai",
            AzureOpenAIConnectionConfig,
            {
                DeploymentKind.LLM: AzureOpenAILLMDeploymentConfig,
                DeploymentKind.REALTIME: AzureOpenAIRealtimeDeploymentConfig,
            },
        )
    )
    registry.register(
        ProviderDefinition(
            "elevenlabs",
            ElevenLabsConnectionConfig,
            {
                DeploymentKind.STT: ElevenLabsSTTDeploymentConfig,
                DeploymentKind.TTS: ElevenLabsTTSDeploymentConfig,
            },
        )
    )
    return registry
