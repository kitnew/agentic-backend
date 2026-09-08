from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.live_component_response_scope import LiveComponentResponseScope
    from ..models.live_component_response_value import LiveComponentResponseValue


T = TypeVar("T", bound="LiveComponentResponse")


@_attrs_define
class LiveComponentResponse:
    """
    Attributes:
        kind (str):
        scope (LiveComponentResponseScope):
        updated_at (datetime.datetime):
        updated_by (str):
        value (LiveComponentResponseValue):
    """

    kind: str
    scope: LiveComponentResponseScope
    updated_at: datetime.datetime
    updated_by: str
    value: LiveComponentResponseValue

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
        from ..models.live_component_response_scope import LiveComponentResponseScope
        from ..models.live_component_response_value import LiveComponentResponseValue

        d = dict(src_dict)
        kind = d.pop("kind")

        scope = LiveComponentResponseScope.from_dict(d.pop("scope"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        updated_by = d.pop("updated_by")

        value = LiveComponentResponseValue.from_dict(d.pop("value"))

        live_component_response = cls(
            kind=kind,
            scope=scope,
            updated_at=updated_at,
            updated_by=updated_by,
            value=value,
        )

        return live_component_response
