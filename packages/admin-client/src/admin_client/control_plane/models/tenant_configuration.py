from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.configuration_status import ConfigurationStatus
    from ..models.tenant_live_configuration import TenantLiveConfiguration
    from ..models.tenant_versioned_configuration import TenantVersionedConfiguration


T = TypeVar("T", bound="TenantConfiguration")


@_attrs_define
class TenantConfiguration:
    """
    Attributes:
        live (TenantLiveConfiguration):
        status (ConfigurationStatus):
        tenant_id (str):
        versioned (TenantVersionedConfiguration):
    """

    live: TenantLiveConfiguration
    status: ConfigurationStatus
    tenant_id: str
    versioned: TenantVersionedConfiguration

    def to_dict(self) -> dict[str, Any]:
        live = self.live.to_dict()

        status = self.status.to_dict()

        tenant_id = self.tenant_id

        versioned = self.versioned.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "live": live,
                "status": status,
                "tenant_id": tenant_id,
                "versioned": versioned,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.configuration_status import ConfigurationStatus
        from ..models.tenant_live_configuration import TenantLiveConfiguration
        from ..models.tenant_versioned_configuration import TenantVersionedConfiguration

        d = dict(src_dict)
        live = TenantLiveConfiguration.from_dict(d.pop("live"))

        status = ConfigurationStatus.from_dict(d.pop("status"))

        tenant_id = d.pop("tenant_id")

        versioned = TenantVersionedConfiguration.from_dict(d.pop("versioned"))

        tenant_configuration = cls(
            live=live,
            status=status,
            tenant_id=tenant_id,
            versioned=versioned,
        )

        return tenant_configuration
