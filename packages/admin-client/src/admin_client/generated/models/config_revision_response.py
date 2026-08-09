from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.config_revision_status import ConfigRevisionStatus

if TYPE_CHECKING:
    from ..models.config_revision_response_config import ConfigRevisionResponseConfig


T = TypeVar("T", bound="ConfigRevisionResponse")


@_attrs_define
class ConfigRevisionResponse:
    """
    Attributes:
        comment (None | str):
        config (ConfigRevisionResponseConfig):
        created_at (datetime.datetime):
        created_by (None | UUID):
        id (UUID):
        published_at (datetime.datetime | None):
        revision_number (int):
        schema_version (int):
        status (ConfigRevisionStatus):
        tenant_id (UUID):
        version (int):
    """

    comment: None | str
    config: ConfigRevisionResponseConfig
    created_at: datetime.datetime
    created_by: None | UUID
    id: UUID
    published_at: datetime.datetime | None
    revision_number: int
    schema_version: int
    status: ConfigRevisionStatus
    tenant_id: UUID
    version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        comment: None | str
        comment = self.comment

        config = self.config.to_dict()

        created_at = self.created_at.isoformat()

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        id = str(self.id)

        published_at: None | str
        if isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        revision_number = self.revision_number

        schema_version = self.schema_version

        status = self.status.value

        tenant_id = str(self.tenant_id)

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "comment": comment,
                "config": config,
                "created_at": created_at,
                "created_by": created_by,
                "id": id,
                "published_at": published_at,
                "revision_number": revision_number,
                "schema_version": schema_version,
                "status": status,
                "tenant_id": tenant_id,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.config_revision_response_config import (
            ConfigRevisionResponseConfig,
        )

        d = dict(src_dict)

        def _parse_comment(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        comment = _parse_comment(d.pop("comment"))

        config = ConfigRevisionResponseConfig.from_dict(d.pop("config"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        id = UUID(d.pop("id"))

        def _parse_published_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_at_type_0 = datetime.datetime.fromisoformat(data)

                return published_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        published_at = _parse_published_at(d.pop("published_at"))

        revision_number = d.pop("revision_number")

        schema_version = d.pop("schema_version")

        status = ConfigRevisionStatus(d.pop("status"))

        tenant_id = UUID(d.pop("tenant_id"))

        version = d.pop("version")

        config_revision_response = cls(
            comment=comment,
            config=config,
            created_at=created_at,
            created_by=created_by,
            id=id,
            published_at=published_at,
            revision_number=revision_number,
            schema_version=schema_version,
            status=status,
            tenant_id=tenant_id,
            version=version,
        )

        config_revision_response.additional_properties = d
        return config_revision_response

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
