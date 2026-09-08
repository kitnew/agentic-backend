from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.business import Business
    from ..models.contact import Contact
    from ..models.localization import Localization


T = TypeVar("T", bound="BusinessInfo")


@_attrs_define
class BusinessInfo:
    """
    Attributes:
        business (Business):
        contact (Contact):
        localization (Localization):
    """

    business: Business
    contact: Contact
    localization: Localization

    def to_dict(self) -> dict[str, Any]:
        business = self.business.to_dict()

        contact = self.contact.to_dict()

        localization = self.localization.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "business": business,
                "contact": contact,
                "localization": localization,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.business import Business
        from ..models.contact import Contact
        from ..models.localization import Localization

        d = dict(src_dict)
        business = Business.from_dict(d.pop("business"))

        contact = Contact.from_dict(d.pop("contact"))

        localization = Localization.from_dict(d.pop("localization"))

        business_info = cls(
            business=business,
            contact=contact,
            localization=localization,
        )

        return business_info
