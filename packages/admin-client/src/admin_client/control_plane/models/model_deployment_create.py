from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.deployment_kind import DeploymentKind

if TYPE_CHECKING:
    from ..models.llm_capabilities_write import LLMCapabilitiesWrite
    from ..models.model_deployment_create_deployment_config import (
        ModelDeploymentCreateDeploymentConfig,
    )
    from ..models.realtime_capabilities_write import RealtimeCapabilitiesWrite
    from ..models.stt_capabilities_write import STTCapabilitiesWrite
    from ..models.tts_capabilities_write import TTSCapabilitiesWrite


T = TypeVar("T", bound="ModelDeploymentCreate")


@_attrs_define
class ModelDeploymentCreate:
    """
    Attributes:
        capabilities (LLMCapabilitiesWrite | RealtimeCapabilitiesWrite | STTCapabilitiesWrite | TTSCapabilitiesWrite):
        connection_ref (UUID):
        deployment_config (ModelDeploymentCreateDeploymentConfig):
        deployment_kind (DeploymentKind):
        key (str):
    """

    capabilities: (
        LLMCapabilitiesWrite
        | RealtimeCapabilitiesWrite
        | STTCapabilitiesWrite
        | TTSCapabilitiesWrite
    )
    connection_ref: UUID
    deployment_config: ModelDeploymentCreateDeploymentConfig
    deployment_kind: DeploymentKind
    key: str

    def to_dict(self) -> dict[str, Any]:
        from ..models.llm_capabilities_write import LLMCapabilitiesWrite
        from ..models.realtime_capabilities_write import RealtimeCapabilitiesWrite
        from ..models.stt_capabilities_write import STTCapabilitiesWrite

        capabilities: dict[str, Any]
        if (
            isinstance(self.capabilities, LLMCapabilitiesWrite)
            or isinstance(self.capabilities, RealtimeCapabilitiesWrite)
            or isinstance(self.capabilities, STTCapabilitiesWrite)
        ):
            capabilities = self.capabilities.to_dict()
        else:
            capabilities = self.capabilities.to_dict()

        connection_ref = str(self.connection_ref)

        deployment_config = self.deployment_config.to_dict()

        deployment_kind = self.deployment_kind.value

        key = self.key

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "capabilities": capabilities,
                "connection_ref": connection_ref,
                "deployment_config": deployment_config,
                "deployment_kind": deployment_kind,
                "key": key,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_capabilities_write import LLMCapabilitiesWrite
        from ..models.model_deployment_create_deployment_config import (
            ModelDeploymentCreateDeploymentConfig,
        )
        from ..models.realtime_capabilities_write import RealtimeCapabilitiesWrite
        from ..models.stt_capabilities_write import STTCapabilitiesWrite
        from ..models.tts_capabilities_write import TTSCapabilitiesWrite

        d = dict(src_dict)

        def _parse_capabilities(
            data: object,
        ) -> (
            LLMCapabilitiesWrite
            | RealtimeCapabilitiesWrite
            | STTCapabilitiesWrite
            | TTSCapabilitiesWrite
        ):
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                capabilities_type_0 = LLMCapabilitiesWrite.from_dict(data)

                return capabilities_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                capabilities_type_1 = RealtimeCapabilitiesWrite.from_dict(data)

                return capabilities_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                capabilities_type_2 = STTCapabilitiesWrite.from_dict(data)

                return capabilities_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            capabilities_type_3 = TTSCapabilitiesWrite.from_dict(data)

            return capabilities_type_3

        capabilities = _parse_capabilities(d.pop("capabilities"))

        connection_ref = UUID(d.pop("connection_ref"))

        deployment_config = ModelDeploymentCreateDeploymentConfig.from_dict(
            d.pop("deployment_config")
        )

        deployment_kind = DeploymentKind(d.pop("deployment_kind"))

        key = d.pop("key")

        model_deployment_create = cls(
            capabilities=capabilities,
            connection_ref=connection_ref,
            deployment_config=deployment_config,
            deployment_kind=deployment_kind,
            key=key,
        )

        return model_deployment_create
