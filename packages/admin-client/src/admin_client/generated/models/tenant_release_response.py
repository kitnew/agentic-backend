from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="TenantReleaseResponse")


@_attrs_define
class TenantReleaseResponse:
    """
    Attributes:
        comment (None | str):
        created_at (datetime.datetime):
        id (UUID):
        release_number (int):
        runtime_bundle_id (UUID):
        source_release_id (None | UUID):
        tenant_id (UUID):
    """

    comment: None | str
    created_at: datetime.datetime
    id: UUID
    release_number: int
    runtime_bundle_id: UUID
    source_release_id: None | UUID
    tenant_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        comment: None | str
        comment = self.comment

        created_at = self.created_at.isoformat()

        id = str(self.id)

        release_number = self.release_number

        runtime_bundle_id = str(self.runtime_bundle_id)

        source_release_id: None | str
        if isinstance(self.source_release_id, UUID):
            source_release_id = str(self.source_release_id)
        else:
            source_release_id = self.source_release_id

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "comment": comment,
                "created_at": created_at,
                "id": id,
                "release_number": release_number,
                "runtime_bundle_id": runtime_bundle_id,
                "source_release_id": source_release_id,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_comment(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        comment = _parse_comment(d.pop("comment"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        id = UUID(d.pop("id"))

        release_number = d.pop("release_number")

        runtime_bundle_id = UUID(d.pop("runtime_bundle_id"))

        def _parse_source_release_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                source_release_id_type_0 = UUID(data)

                return source_release_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        source_release_id = _parse_source_release_id(d.pop("source_release_id"))

        tenant_id = UUID(d.pop("tenant_id"))

        tenant_release_response = cls(
            comment=comment,
            created_at=created_at,
            id=id,
            release_number=release_number,
            runtime_bundle_id=runtime_bundle_id,
            source_release_id=source_release_id,
            tenant_id=tenant_id,
        )

        tenant_release_response.additional_properties = d
        return tenant_release_response

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
