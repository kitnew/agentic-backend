from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.conversation_message_role import ConversationMessageRole

T = TypeVar("T", bound="ConversationMessageResponse")


@_attrs_define
class ConversationMessageResponse:
    """
    Attributes:
        content (str):
        conversation_id (UUID):
        interrupted (bool):
        message_id (UUID):
        persisted_at (datetime.datetime):
        role (ConversationMessageRole):
        sequence_number (int):
        source_created_at (datetime.datetime | None):
    """

    content: str
    conversation_id: UUID
    interrupted: bool
    message_id: UUID
    persisted_at: datetime.datetime
    role: ConversationMessageRole
    sequence_number: int
    source_created_at: datetime.datetime | None

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        conversation_id = str(self.conversation_id)

        interrupted = self.interrupted

        message_id = str(self.message_id)

        persisted_at = self.persisted_at.isoformat()

        role = self.role.value

        sequence_number = self.sequence_number

        source_created_at: None | str
        if isinstance(self.source_created_at, datetime.datetime):
            source_created_at = self.source_created_at.isoformat()
        else:
            source_created_at = self.source_created_at

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "content": content,
                "conversation_id": conversation_id,
                "interrupted": interrupted,
                "message_id": message_id,
                "persisted_at": persisted_at,
                "role": role,
                "sequence_number": sequence_number,
                "source_created_at": source_created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        content = d.pop("content")

        conversation_id = UUID(d.pop("conversation_id"))

        interrupted = d.pop("interrupted")

        message_id = UUID(d.pop("message_id"))

        persisted_at = datetime.datetime.fromisoformat(d.pop("persisted_at"))

        role = ConversationMessageRole(d.pop("role"))

        sequence_number = d.pop("sequence_number")

        def _parse_source_created_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                source_created_at_type_0 = datetime.datetime.fromisoformat(data)

                return source_created_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        source_created_at = _parse_source_created_at(d.pop("source_created_at"))

        conversation_message_response = cls(
            content=content,
            conversation_id=conversation_id,
            interrupted=interrupted,
            message_id=message_id,
            persisted_at=persisted_at,
            role=role,
            sequence_number=sequence_number,
            source_created_at=source_created_at,
        )

        return conversation_message_response
