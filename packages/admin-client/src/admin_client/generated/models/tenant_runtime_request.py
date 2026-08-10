from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_runtime_override import TenantRuntimeOverride


T = TypeVar("T", bound="TenantRuntimeRequest")


@_attrs_define
class TenantRuntimeRequest:
    """
    Attributes:
        settings (TenantRuntimeOverride):
    """

    settings: TenantRuntimeOverride

    def to_dict(self) -> dict[str, Any]:
        settings = self.settings.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "settings": settings,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_runtime_override import TenantRuntimeOverride

        d = dict(src_dict)
        settings = TenantRuntimeOverride.from_dict(d.pop("settings"))

        tenant_runtime_request = cls(
            settings=settings,
        )

        return tenant_runtime_request
