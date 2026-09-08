from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.system_live_component_response_value import (
        SystemLiveComponentResponseValue,
    )
    from ..models.system_scope_response import SystemScopeResponse


T = TypeVar("T", bound="SystemLiveComponentResponse")


@_attrs_define
class SystemLiveComponentResponse:
    """
    Attributes:
        kind (str):
        scope (SystemScopeResponse):
        updated_at (datetime.datetime):
        updated_by (str):
        value (SystemLiveComponentResponseValue):
    """

    kind: str
    scope: SystemScopeResponse
    updated_at: datetime.datetime
    updated_by: str
    value: SystemLiveComponentResponseValue

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        scope = self.scope.to_dict()

        updated_at = self.updated_at.isoformat()

        updated_by = self.updated_by

        value = self.value.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "scope": scope,
                "updated_at": updated_at,
                "updated_by": updated_by,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.system_live_component_response_value import (
            SystemLiveComponentResponseValue,
        )
        from ..models.system_scope_response import SystemScopeResponse

        d = dict(src_dict)
        kind = d.pop("kind")

        scope = SystemScopeResponse.from_dict(d.pop("scope"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        updated_by = d.pop("updated_by")

        value = SystemLiveComponentResponseValue.from_dict(d.pop("value"))

        system_live_component_response = cls(
            kind=kind,
            scope=scope,
            updated_at=updated_at,
            updated_by=updated_by,
            value=value,
        )

        return system_live_component_response
