from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="UpdatePromptSetDraftRequest")


@_attrs_define
class UpdatePromptSetDraftRequest:
    """
    Attributes:
        knowledge_base_revision_id (UUID):
        profile_prompt_revision_id (UUID):
        system_prompt_revision_id (UUID):
        tenant_prompt_revision_id (UUID):
    """

    knowledge_base_revision_id: UUID
    profile_prompt_revision_id: UUID
    system_prompt_revision_id: UUID
    tenant_prompt_revision_id: UUID

    def to_dict(self) -> dict[str, Any]:
        knowledge_base_revision_id = str(self.knowledge_base_revision_id)

        profile_prompt_revision_id = str(self.profile_prompt_revision_id)

        system_prompt_revision_id = str(self.system_prompt_revision_id)

        tenant_prompt_revision_id = str(self.tenant_prompt_revision_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "knowledge_base_revision_id": knowledge_base_revision_id,
                "profile_prompt_revision_id": profile_prompt_revision_id,
                "system_prompt_revision_id": system_prompt_revision_id,
                "tenant_prompt_revision_id": tenant_prompt_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        knowledge_base_revision_id = UUID(d.pop("knowledge_base_revision_id"))

        profile_prompt_revision_id = UUID(d.pop("profile_prompt_revision_id"))

        system_prompt_revision_id = UUID(d.pop("system_prompt_revision_id"))

        tenant_prompt_revision_id = UUID(d.pop("tenant_prompt_revision_id"))

        update_prompt_set_draft_request = cls(
            knowledge_base_revision_id=knowledge_base_revision_id,
            profile_prompt_revision_id=profile_prompt_revision_id,
            system_prompt_revision_id=system_prompt_revision_id,
            tenant_prompt_revision_id=tenant_prompt_revision_id,
        )

        return update_prompt_set_draft_request
