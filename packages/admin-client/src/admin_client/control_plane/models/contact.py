from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="Contact")


@_attrs_define
class Contact:
    """
    Attributes:
        emails (list[str]):
        phones (list[str]):
        address (None | str | Unset):
        website (None | str | Unset):
    """

    emails: list[str]
    phones: list[str]
    address: None | str | Unset = UNSET
    website: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        emails = self.emails

        phones = self.phones

        address: None | str | Unset
        if isinstance(self.address, Unset):
            address = UNSET
        else:
            address = self.address

        website: None | str | Unset
        if isinstance(self.website, Unset):
            website = UNSET
        else:
            website = self.website

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "emails": emails,
                "phones": phones,
            }
        )
        if address is not UNSET:
            field_dict["address"] = address
        if website is not UNSET:
            field_dict["website"] = website

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        emails = cast(list[str], d.pop("emails"))

        phones = cast(list[str], d.pop("phones"))

        def _parse_address(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        address = _parse_address(d.pop("address", UNSET))

        def _parse_website(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        website = _parse_website(d.pop("website", UNSET))

        contact = cls(
            emails=emails,
            phones=phones,
            address=address,
            website=website,
        )

        return contact
