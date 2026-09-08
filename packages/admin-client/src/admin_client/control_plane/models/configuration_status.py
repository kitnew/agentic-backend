from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ConfigurationStatus")


@_attrs_define
class ConfigurationStatus:
    """
    Attributes:
        has_drafts (bool):
        publishable (bool):
    """

    has_drafts: bool
    publishable: bool

    def to_dict(self) -> dict[str, Any]:
        has_drafts = self.has_drafts

        publishable = self.publishable

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "has_drafts": has_drafts,
                "publishable": publishable,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        has_drafts = d.pop("has_drafts")

        publishable = d.pop("publishable")

        configuration_status = cls(
            has_drafts=has_drafts,
            publishable=publishable,
        )

        return configuration_status
