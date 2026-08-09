from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CreateTestVoiceSessionRequest")


@_attrs_define
class CreateTestVoiceSessionRequest:
    """
    Attributes:
        tenant_id (UUID):
    """

    tenant_id: UUID

    def to_dict(self) -> dict[str, Any]:
        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        tenant_id = UUID(d.pop("tenant_id"))

        create_test_voice_session_request = cls(
            tenant_id=tenant_id,
        )

        return create_test_voice_session_request
