from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.validate_config_request_config import ValidateConfigRequestConfig


T = TypeVar("T", bound="ValidateConfigRequest")


@_attrs_define
class ValidateConfigRequest:
    """
    Attributes:
        config (ValidateConfigRequestConfig):
        schema_version (int):
    """

    config: ValidateConfigRequestConfig
    schema_version: int

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        schema_version = self.schema_version

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "config": config,
                "schema_version": schema_version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.validate_config_request_config import ValidateConfigRequestConfig

        d = dict(src_dict)
        config = ValidateConfigRequestConfig.from_dict(d.pop("config"))

        schema_version = d.pop("schema_version")

        validate_config_request = cls(
            config=config,
            schema_version=schema_version,
        )

        return validate_config_request
