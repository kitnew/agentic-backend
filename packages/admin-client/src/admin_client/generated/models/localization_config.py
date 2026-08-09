from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="LocalizationConfig")


@_attrs_define
class LocalizationConfig:
    """
    Attributes:
        default_locale (str):
        timezone (str):
    """

    default_locale: str
    timezone: str

    def to_dict(self) -> dict[str, Any]:
        default_locale = self.default_locale

        timezone = self.timezone

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "default_locale": default_locale,
                "timezone": timezone,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        default_locale = d.pop("default_locale")

        timezone = d.pop("timezone")

        localization_config = cls(
            default_locale=default_locale,
            timezone=timezone,
        )

        return localization_config
