from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_draft_state_value_type_0 import PlatformDraftStateValueType0


T = TypeVar("T", bound="PlatformDraftState")


@_attrs_define
class PlatformDraftState:
    """
    Attributes:
        id (str):
        value (PlatformDraftStateValueType0 | str):
        version (int):
    """

    id: str
    value: PlatformDraftStateValueType0 | str
    version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_draft_state_value_type_0 import (
            PlatformDraftStateValueType0,
        )

        id = self.id

        value: dict[str, Any] | str
        if isinstance(self.value, PlatformDraftStateValueType0):
            value = self.value.to_dict()
        else:
            value = self.value

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "value": value,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_draft_state_value_type_0 import (
            PlatformDraftStateValueType0,
        )

        d = dict(src_dict)
        id = d.pop("id")

        def _parse_value(data: object) -> PlatformDraftStateValueType0 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                value_type_0 = PlatformDraftStateValueType0.from_dict(data)

                return value_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(PlatformDraftStateValueType0 | str, data)

        value = _parse_value(d.pop("value"))

        version = d.pop("version")

        platform_draft_state = cls(
            id=id,
            value=value,
            version=version,
        )

        platform_draft_state.additional_properties = d
        return platform_draft_state

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
