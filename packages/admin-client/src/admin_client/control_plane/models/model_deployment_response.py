from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.deployment_kind import DeploymentKind

if TYPE_CHECKING:
    from ..models.llm_capabilities_write import LLMCapabilitiesWrite
    from ..models.model_deployment_response_deployment_config import (
        ModelDeploymentResponseDeploymentConfig,
    )
    from ..models.realtime_capabilities_write import RealtimeCapabilitiesWrite
    from ..models.stt_capabilities_write import STTCapabilitiesWrite
    from ..models.tts_capabilities_write import TTSCapabilitiesWrite


T = TypeVar("T", bound="ModelDeploymentResponse")


@_attrs_define
class ModelDeploymentResponse:
    """
    Attributes:
        capabilities (LLMCapabilitiesWrite | RealtimeCapabilitiesWrite | STTCapabilitiesWrite | TTSCapabilitiesWrite):
        connection_ref (UUID):
        created_at (datetime.datetime):
        deployment_config (ModelDeploymentResponseDeploymentConfig):
        deployment_kind (DeploymentKind):
        enabled (bool):
        id (UUID):
        key (str):
        updated_at (datetime.datetime):
    """

    capabilities: (
        LLMCapabilitiesWrite
        | RealtimeCapabilitiesWrite
        | STTCapabilitiesWrite
        | TTSCapabilitiesWrite
    )
    connection_ref: UUID
    created_at: datetime.datetime
    deployment_config: ModelDeploymentResponseDeploymentConfig
    deployment_kind: DeploymentKind
    enabled: bool
    id: UUID
    key: str
    updated_at: datetime.datetime

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

        created_at = self.created_at.isoformat()

        deployment_config = self.deployment_config.to_dict()

        deployment_kind = self.deployment_kind.value

        enabled = self.enabled

        id = str(self.id)

        key = self.key

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "capabilities": capabilities,
                "connection_ref": connection_ref,
                "created_at": created_at,
                "deployment_config": deployment_config,
                "deployment_kind": deployment_kind,
                "enabled": enabled,
                "id": id,
                "key": key,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_capabilities_write import LLMCapabilitiesWrite
        from ..models.model_deployment_response_deployment_config import (
            ModelDeploymentResponseDeploymentConfig,
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

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        deployment_config = ModelDeploymentResponseDeploymentConfig.from_dict(
            d.pop("deployment_config")
        )

        deployment_kind = DeploymentKind(d.pop("deployment_kind"))

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        model_deployment_response = cls(
            capabilities=capabilities,
            connection_ref=connection_ref,
            created_at=created_at,
            deployment_config=deployment_config,
            deployment_kind=deployment_kind,
            enabled=enabled,
            id=id,
            key=key,
            updated_at=updated_at,
        )

        return model_deployment_response
