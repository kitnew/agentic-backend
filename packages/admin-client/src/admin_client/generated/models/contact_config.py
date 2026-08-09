from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="ContactConfig")


@_attrs_define
class ContactConfig:
    """
    Attributes:
        address (None | str | Unset):
        emails (list[str] | Unset):
        phones (list[str] | Unset):
        website (None | str | Unset):
    """

    address: None | str | Unset = UNSET
    emails: list[str] | Unset = UNSET
    phones: list[str] | Unset = UNSET
    website: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        address: None | str | Unset
        if isinstance(self.address, Unset):
            address = UNSET
        else:
            address = self.address

        emails: list[str] | Unset = UNSET
        if not isinstance(self.emails, Unset):
            emails = self.emails

        phones: list[str] | Unset = UNSET
        if not isinstance(self.phones, Unset):
            phones = self.phones

        website: None | str | Unset
        if isinstance(self.website, Unset):
            website = UNSET
        else:
            website = self.website

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if address is not UNSET:
            field_dict["address"] = address
        if emails is not UNSET:
            field_dict["emails"] = emails
        if phones is not UNSET:
            field_dict["phones"] = phones
        if website is not UNSET:
            field_dict["website"] = website

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_address(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        address = _parse_address(d.pop("address", UNSET))

        emails = cast(list[str], d.pop("emails", UNSET))

        phones = cast(list[str], d.pop("phones", UNSET))

        def _parse_website(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        website = _parse_website(d.pop("website", UNSET))

        contact_config = cls(
            address=address,
            emails=emails,
            phones=phones,
            website=website,
        )

        return contact_config
