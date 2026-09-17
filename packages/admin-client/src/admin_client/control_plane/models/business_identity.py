from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.business import Business
    from ..models.business_link import BusinessLink
    from ..models.contact import Contact
    from ..models.localization import Localization


T = TypeVar("T", bound="BusinessIdentity")


@_attrs_define
class BusinessIdentity:
    """
    Attributes:
        business (Business):
        contact (Contact):
        localization (Localization):
        links (list[BusinessLink] | Unset):
    """

    business: Business
    contact: Contact
    localization: Localization
    links: list[BusinessLink] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        business = self.business.to_dict()

        contact = self.contact.to_dict()

        localization = self.localization.to_dict()

        links: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.links, Unset):
            links = []
            for links_item_data in self.links:
                links_item = links_item_data.to_dict()
                links.append(links_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "business": business,
                "contact": contact,
                "localization": localization,
            }
        )
        if links is not UNSET:
            field_dict["links"] = links

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.business import Business
        from ..models.business_link import BusinessLink
        from ..models.contact import Contact
        from ..models.localization import Localization

        d = dict(src_dict)
        business = Business.from_dict(d.pop("business"))

        contact = Contact.from_dict(d.pop("contact"))

        localization = Localization.from_dict(d.pop("localization"))

        _links = d.pop("links", UNSET)
        links: list[BusinessLink] | Unset = UNSET
        if _links is not UNSET:
            links = []
            for links_item_data in _links:
                links_item = BusinessLink.from_dict(links_item_data)

                links.append(links_item)

        business_identity = cls(
            business=business,
            contact=contact,
            localization=localization,
            links=links,
        )

        return business_identity
