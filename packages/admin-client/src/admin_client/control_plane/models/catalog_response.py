from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.catalog_response_status import CatalogResponseStatus

T = TypeVar("T", bound="CatalogResponse")


@_attrs_define
class CatalogResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        description (str):
        key (str):
        name (str):
        status (CatalogResponseStatus):
        updated_at (datetime.datetime):
    """

    created_at: datetime.datetime
    description: str
    key: str
    name: str
    status: CatalogResponseStatus
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        description = self.description

        key = self.key

        name = self.name

        status = self.status.value

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "created_at": created_at,
                "description": description,
                "key": key,
                "name": name,
                "status": status,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        description = d.pop("description")

        key = d.pop("key")

        name = d.pop("name")

        status = CatalogResponseStatus(d.pop("status"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        catalog_response = cls(
            created_at=created_at,
            description=description,
            key=key,
            name=name,
            status=status,
            updated_at=updated_at,
        )

        return catalog_response
