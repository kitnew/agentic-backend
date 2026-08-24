from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.tenant_capabilities_authoring_capabilities import (
        TenantCapabilitiesAuthoringCapabilities,
    )


T = TypeVar("T", bound="TenantCapabilitiesAuthoring")


@_attrs_define
class TenantCapabilitiesAuthoring:
    """
    Attributes:
        capabilities (TenantCapabilitiesAuthoringCapabilities | Unset):
    """

    capabilities: TenantCapabilitiesAuthoringCapabilities | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        capabilities: dict[str, Any] | Unset = UNSET
        if not isinstance(self.capabilities, Unset):
            capabilities = self.capabilities.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if capabilities is not UNSET:
            field_dict["capabilities"] = capabilities

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_capabilities_authoring_capabilities import (
            TenantCapabilitiesAuthoringCapabilities,
        )

        d = dict(src_dict)
        _capabilities = d.pop("capabilities", UNSET)
        capabilities: TenantCapabilitiesAuthoringCapabilities | Unset
        if isinstance(_capabilities, Unset):
            capabilities = UNSET
        else:
            capabilities = TenantCapabilitiesAuthoringCapabilities.from_dict(
                _capabilities
            )

        tenant_capabilities_authoring = cls(
            capabilities=capabilities,
        )

        return tenant_capabilities_authoring
