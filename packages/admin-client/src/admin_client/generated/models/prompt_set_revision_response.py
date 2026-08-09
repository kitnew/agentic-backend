from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="PromptSetRevisionResponse")


@_attrs_define
class PromptSetRevisionResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        id (UUID):
        knowledge_base_revision_id (UUID):
        profile_prompt_revision_id (UUID):
        published_at (datetime.datetime | None):
        revision_number (int):
        status (str):
        system_prompt_revision_id (UUID):
        tenant_id (UUID):
        tenant_prompt_revision_id (UUID):
        version (int):
    """

    created_at: datetime.datetime
    id: UUID
    knowledge_base_revision_id: UUID
    profile_prompt_revision_id: UUID
    published_at: datetime.datetime | None
    revision_number: int
    status: str
    system_prompt_revision_id: UUID
    tenant_id: UUID
    tenant_prompt_revision_id: UUID
    version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        id = str(self.id)

        knowledge_base_revision_id = str(self.knowledge_base_revision_id)

        profile_prompt_revision_id = str(self.profile_prompt_revision_id)

        published_at: None | str
        if isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        revision_number = self.revision_number

        status = self.status

        system_prompt_revision_id = str(self.system_prompt_revision_id)

        tenant_id = str(self.tenant_id)

        tenant_prompt_revision_id = str(self.tenant_prompt_revision_id)

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "id": id,
                "knowledge_base_revision_id": knowledge_base_revision_id,
                "profile_prompt_revision_id": profile_prompt_revision_id,
                "published_at": published_at,
                "revision_number": revision_number,
                "status": status,
                "system_prompt_revision_id": system_prompt_revision_id,
                "tenant_id": tenant_id,
                "tenant_prompt_revision_id": tenant_prompt_revision_id,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        id = UUID(d.pop("id"))

        knowledge_base_revision_id = UUID(d.pop("knowledge_base_revision_id"))

        profile_prompt_revision_id = UUID(d.pop("profile_prompt_revision_id"))

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

        status = d.pop("status")

        system_prompt_revision_id = UUID(d.pop("system_prompt_revision_id"))

        tenant_id = UUID(d.pop("tenant_id"))

        tenant_prompt_revision_id = UUID(d.pop("tenant_prompt_revision_id"))

        version = d.pop("version")

        prompt_set_revision_response = cls(
            created_at=created_at,
            id=id,
            knowledge_base_revision_id=knowledge_base_revision_id,
            profile_prompt_revision_id=profile_prompt_revision_id,
            published_at=published_at,
            revision_number=revision_number,
            status=status,
            system_prompt_revision_id=system_prompt_revision_id,
            tenant_id=tenant_id,
            tenant_prompt_revision_id=tenant_prompt_revision_id,
            version=version,
        )

        prompt_set_revision_response.additional_properties = d
        return prompt_set_revision_response

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
