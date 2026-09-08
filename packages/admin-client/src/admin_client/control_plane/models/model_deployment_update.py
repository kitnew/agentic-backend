from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.llm_capabilities_write import LLMCapabilitiesWrite
    from ..models.model_deployment_update_deployment_config import (
        ModelDeploymentUpdateDeploymentConfig,
    )
    from ..models.realtime_capabilities_write import RealtimeCapabilitiesWrite
    from ..models.stt_capabilities_write import STTCapabilitiesWrite
    from ..models.tts_capabilities_write import TTSCapabilitiesWrite


T = TypeVar("T", bound="ModelDeploymentUpdate")


@_attrs_define
class ModelDeploymentUpdate:
    """
    Attributes:
        capabilities (LLMCapabilitiesWrite | RealtimeCapabilitiesWrite | STTCapabilitiesWrite | TTSCapabilitiesWrite):
        connection_ref (UUID):
        deployment_config (ModelDeploymentUpdateDeploymentConfig):
    """

    capabilities: (
        LLMCapabilitiesWrite
        | RealtimeCapabilitiesWrite
        | STTCapabilitiesWrite
        | TTSCapabilitiesWrite
    )
    connection_ref: UUID
    deployment_config: ModelDeploymentUpdateDeploymentConfig

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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "capabilities": capabilities,
                "connection_ref": connection_ref,
                "deployment_config": deployment_config,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_capabilities_write import LLMCapabilitiesWrite
        from ..models.model_deployment_update_deployment_config import (
            ModelDeploymentUpdateDeploymentConfig,
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

        deployment_config = ModelDeploymentUpdateDeploymentConfig.from_dict(
            d.pop("deployment_config")
        )

        model_deployment_update = cls(
            capabilities=capabilities,
            connection_ref=connection_ref,
            deployment_config=deployment_config,
        )

        return model_deployment_update
