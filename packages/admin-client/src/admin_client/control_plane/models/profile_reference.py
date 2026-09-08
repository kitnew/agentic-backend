from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ProfileReference")


@_attrs_define
class ProfileReference:
    """
    Attributes:
        profile_key (str):
    """

    profile_key: str

    def to_dict(self) -> dict[str, Any]:
        profile_key = self.profile_key

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "profile_key": profile_key,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        profile_key = d.pop("profile_key")

        profile_reference = cls(
            profile_key=profile_key,
        )

        return profile_reference
