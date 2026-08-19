from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.integration_provider import IntegrationProvider
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.create_integration_connection_request_config import (
        CreateIntegrationConnectionRequestConfig,
    )


T = TypeVar("T", bound="CreateIntegrationConnectionRequest")


@_attrs_define
class CreateIntegrationConnectionRequest:
    """
    Attributes:
        key (str):
        provider (IntegrationProvider):
        config (CreateIntegrationConnectionRequestConfig | Unset):
    """

    key: str
    provider: IntegrationProvider
    config: CreateIntegrationConnectionRequestConfig | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        provider = self.provider.value

        config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config, Unset):
            config = self.config.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "provider": provider,
            }
        )
        if config is not UNSET:
            field_dict["config"] = config

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.create_integration_connection_request_config import (
            CreateIntegrationConnectionRequestConfig,
        )

        d = dict(src_dict)
        key = d.pop("key")

        provider = IntegrationProvider(d.pop("provider"))

        _config = d.pop("config", UNSET)
        config: CreateIntegrationConnectionRequestConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = CreateIntegrationConnectionRequestConfig.from_dict(_config)

        create_integration_connection_request = cls(
            key=key,
            provider=provider,
            config=config,
        )

        return create_integration_connection_request
