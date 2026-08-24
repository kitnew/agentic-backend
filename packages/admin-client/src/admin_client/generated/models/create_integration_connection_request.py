from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.create_integration_connection_request_kind import (
    CreateIntegrationConnectionRequestKind,
)

T = TypeVar("T", bound="CreateIntegrationConnectionRequest")


@_attrs_define
class CreateIntegrationConnectionRequest:
    """
    Attributes:
        key (str):
        kind (CreateIntegrationConnectionRequestKind):
    """

    key: str
    kind: CreateIntegrationConnectionRequestKind

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        kind = self.kind.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "kind": kind,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        key = d.pop("key")

        kind = CreateIntegrationConnectionRequestKind(d.pop("kind"))

        create_integration_connection_request = cls(
            key=key,
            kind=kind,
        )

        return create_integration_connection_request
