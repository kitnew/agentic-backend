from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.integration_connection_status import IntegrationConnectionStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.update_integration_connection_request_config_type_0 import (
        UpdateIntegrationConnectionRequestConfigType0,
    )


T = TypeVar("T", bound="UpdateIntegrationConnectionRequest")


@_attrs_define
class UpdateIntegrationConnectionRequest:
    """
    Attributes:
        config (None | Unset | UpdateIntegrationConnectionRequestConfigType0):
        status (IntegrationConnectionStatus | None | Unset):
    """

    config: None | Unset | UpdateIntegrationConnectionRequestConfigType0 = UNSET
    status: IntegrationConnectionStatus | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.update_integration_connection_request_config_type_0 import (
            UpdateIntegrationConnectionRequestConfigType0,
        )

        config: dict[str, Any] | None | Unset
        if isinstance(self.config, Unset):
            config = UNSET
        elif isinstance(self.config, UpdateIntegrationConnectionRequestConfigType0):
            config = self.config.to_dict()
        else:
            config = self.config

        status: None | str | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        elif isinstance(self.status, IntegrationConnectionStatus):
            status = self.status.value
        else:
            status = self.status

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if config is not UNSET:
            field_dict["config"] = config
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.update_integration_connection_request_config_type_0 import (
            UpdateIntegrationConnectionRequestConfigType0,
        )

        d = dict(src_dict)

        def _parse_config(
            data: object,
        ) -> None | Unset | UpdateIntegrationConnectionRequestConfigType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                config_type_0 = UpdateIntegrationConnectionRequestConfigType0.from_dict(
                    data
                )

                return config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | Unset | UpdateIntegrationConnectionRequestConfigType0, data
            )

        config = _parse_config(d.pop("config", UNSET))

        def _parse_status(data: object) -> IntegrationConnectionStatus | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                status_type_0 = IntegrationConnectionStatus(data)

                return status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(IntegrationConnectionStatus | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        update_integration_connection_request = cls(
            config=config,
            status=status,
        )

        return update_integration_connection_request
