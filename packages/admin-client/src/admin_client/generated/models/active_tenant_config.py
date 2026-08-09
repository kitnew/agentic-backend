from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_config_v1 import TenantConfigV1
    from ..models.tenant_config_v2 import TenantConfigV2
    from ..models.tenant_config_v3 import TenantConfigV3


T = TypeVar("T", bound="ActiveTenantConfig")


@_attrs_define
class ActiveTenantConfig:
    """
    Attributes:
        config (TenantConfigV1 | TenantConfigV2 | TenantConfigV3):
        published_at (datetime.datetime):
        revision_id (UUID):
        revision_number (int):
        tenant_id (UUID):
    """

    config: TenantConfigV1 | TenantConfigV2 | TenantConfigV3
    published_at: datetime.datetime
    revision_id: UUID
    revision_number: int
    tenant_id: UUID

    def to_dict(self) -> dict[str, Any]:
        from ..models.tenant_config_v1 import TenantConfigV1
        from ..models.tenant_config_v2 import TenantConfigV2

        config: dict[str, Any]
        if isinstance(self.config, TenantConfigV1) or isinstance(
            self.config, TenantConfigV2
        ):
            config = self.config.to_dict()
        else:
            config = self.config.to_dict()

        published_at = self.published_at.isoformat()

        revision_id = str(self.revision_id)

        revision_number = self.revision_number

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "config": config,
                "published_at": published_at,
                "revision_id": revision_id,
                "revision_number": revision_number,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_config_v1 import TenantConfigV1
        from ..models.tenant_config_v2 import TenantConfigV2
        from ..models.tenant_config_v3 import TenantConfigV3

        d = dict(src_dict)

        def _parse_config(
            data: object,
        ) -> TenantConfigV1 | TenantConfigV2 | TenantConfigV3:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                config_type_0 = TenantConfigV1.from_dict(data)

                return config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                config_type_1 = TenantConfigV2.from_dict(data)

                return config_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            config_type_2 = TenantConfigV3.from_dict(data)

            return config_type_2

        config = _parse_config(d.pop("config"))

        published_at = datetime.datetime.fromisoformat(d.pop("published_at"))

        revision_id = UUID(d.pop("revision_id"))

        revision_number = d.pop("revision_number")

        tenant_id = UUID(d.pop("tenant_id"))

        active_tenant_config = cls(
            config=config,
            published_at=published_at,
            revision_id=revision_id,
            revision_number=revision_number,
            tenant_id=tenant_id,
        )

        return active_tenant_config
