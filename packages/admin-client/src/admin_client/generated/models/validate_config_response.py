from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.validate_config_response_normalized_config_type_0 import (
        ValidateConfigResponseNormalizedConfigType0,
    )
    from ..models.validation_issue import ValidationIssue


T = TypeVar("T", bound="ValidateConfigResponse")


@_attrs_define
class ValidateConfigResponse:
    """
    Attributes:
        valid (bool):
        errors (list[ValidationIssue] | Unset):
        normalized_config (None | Unset | ValidateConfigResponseNormalizedConfigType0):
    """

    valid: bool
    errors: list[ValidationIssue] | Unset = UNSET
    normalized_config: None | Unset | ValidateConfigResponseNormalizedConfigType0 = (
        UNSET
    )
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.validate_config_response_normalized_config_type_0 import (
            ValidateConfigResponseNormalizedConfigType0,
        )

        valid = self.valid

        errors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = []
            for errors_item_data in self.errors:
                errors_item = errors_item_data.to_dict()
                errors.append(errors_item)

        normalized_config: dict[str, Any] | None | Unset
        if isinstance(self.normalized_config, Unset):
            normalized_config = UNSET
        elif isinstance(
            self.normalized_config, ValidateConfigResponseNormalizedConfigType0
        ):
            normalized_config = self.normalized_config.to_dict()
        else:
            normalized_config = self.normalized_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "valid": valid,
            }
        )
        if errors is not UNSET:
            field_dict["errors"] = errors
        if normalized_config is not UNSET:
            field_dict["normalized_config"] = normalized_config

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.validate_config_response_normalized_config_type_0 import (
            ValidateConfigResponseNormalizedConfigType0,
        )
        from ..models.validation_issue import ValidationIssue

        d = dict(src_dict)
        valid = d.pop("valid")

        _errors = d.pop("errors", UNSET)
        errors: list[ValidationIssue] | Unset = UNSET
        if _errors is not UNSET:
            errors = []
            for errors_item_data in _errors:
                errors_item = ValidationIssue.from_dict(errors_item_data)

                errors.append(errors_item)

        def _parse_normalized_config(
            data: object,
        ) -> None | Unset | ValidateConfigResponseNormalizedConfigType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                normalized_config_type_0 = (
                    ValidateConfigResponseNormalizedConfigType0.from_dict(data)
                )

                return normalized_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | Unset | ValidateConfigResponseNormalizedConfigType0, data
            )

        normalized_config = _parse_normalized_config(d.pop("normalized_config", UNSET))

        validate_config_response = cls(
            valid=valid,
            errors=errors,
            normalized_config=normalized_config,
        )

        validate_config_response.additional_properties = d
        return validate_config_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
