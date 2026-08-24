from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.telephony_claim_status import TelephonyClaimStatus
    from ..models.telephony_did_state import TelephonyDidState
    from ..models.telephony_provisioning_status_response import (
        TelephonyProvisioningStatusResponse,
    )


T = TypeVar("T", bound="TenantTelephonyStatus")


@_attrs_define
class TenantTelephonyStatus:
    """
    Attributes:
        claim (TelephonyClaimStatus):
        draft (None | TelephonyDidState):
        provisioning (TelephonyProvisioningStatusResponse):
        publication (str):
        published (None | TelephonyDidState):
        tenant_id (UUID):
    """

    claim: TelephonyClaimStatus
    draft: None | TelephonyDidState
    provisioning: TelephonyProvisioningStatusResponse
    publication: str
    published: None | TelephonyDidState
    tenant_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.telephony_did_state import TelephonyDidState

        claim = self.claim.to_dict()

        draft: dict[str, Any] | None
        if isinstance(self.draft, TelephonyDidState):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        provisioning = self.provisioning.to_dict()

        publication = self.publication

        published: dict[str, Any] | None
        if isinstance(self.published, TelephonyDidState):
            published = self.published.to_dict()
        else:
            published = self.published

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "claim": claim,
                "draft": draft,
                "provisioning": provisioning,
                "publication": publication,
                "published": published,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.telephony_claim_status import TelephonyClaimStatus
        from ..models.telephony_did_state import TelephonyDidState
        from ..models.telephony_provisioning_status_response import (
            TelephonyProvisioningStatusResponse,
        )

        d = dict(src_dict)
        claim = TelephonyClaimStatus.from_dict(d.pop("claim"))

        def _parse_draft(data: object) -> None | TelephonyDidState:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = TelephonyDidState.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TelephonyDidState, data)

        draft = _parse_draft(d.pop("draft"))

        provisioning = TelephonyProvisioningStatusResponse.from_dict(
            d.pop("provisioning")
        )

        publication = d.pop("publication")

        def _parse_published(data: object) -> None | TelephonyDidState:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                published_type_0 = TelephonyDidState.from_dict(data)

                return published_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TelephonyDidState, data)

        published = _parse_published(d.pop("published"))

        tenant_id = UUID(d.pop("tenant_id"))

        tenant_telephony_status = cls(
            claim=claim,
            draft=draft,
            provisioning=provisioning,
            publication=publication,
            published=published,
            tenant_id=tenant_id,
        )

        tenant_telephony_status.additional_properties = d
        return tenant_telephony_status

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
