from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="PlatformReleaseResponse")


@_attrs_define
class PlatformReleaseResponse:
    """
    Attributes:
        id (str):
        release_number (int):
        runtime_revision_id (str):
        system_prompt_revision_id (str):
    """

    id: str
    release_number: int
    runtime_revision_id: str
    system_prompt_revision_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        release_number = self.release_number

        runtime_revision_id = self.runtime_revision_id

        system_prompt_revision_id = self.system_prompt_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "release_number": release_number,
                "runtime_revision_id": runtime_revision_id,
                "system_prompt_revision_id": system_prompt_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        id = d.pop("id")

        release_number = d.pop("release_number")

        runtime_revision_id = d.pop("runtime_revision_id")

        system_prompt_revision_id = d.pop("system_prompt_revision_id")

        platform_release_response = cls(
            id=id,
            release_number=release_number,
            runtime_revision_id=runtime_revision_id,
            system_prompt_revision_id=system_prompt_revision_id,
        )

        platform_release_response.additional_properties = d
        return platform_release_response

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
