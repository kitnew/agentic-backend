from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.conversation_persistence_status import ConversationPersistenceStatus

if TYPE_CHECKING:
    from ..models.conversation_message_response import ConversationMessageResponse


T = TypeVar("T", bound="ConversationResponse")


@_attrs_define
class ConversationResponse:
    """
    Attributes:
        call_session_id (UUID):
        closed_at (datetime.datetime | None):
        conversation_id (UUID):
        created_at (datetime.datetime):
        messages (list[ConversationMessageResponse]):
        status (ConversationPersistenceStatus):
    """

    call_session_id: UUID
    closed_at: datetime.datetime | None
    conversation_id: UUID
    created_at: datetime.datetime
    messages: list[ConversationMessageResponse]
    status: ConversationPersistenceStatus

    def to_dict(self) -> dict[str, Any]:
        call_session_id = str(self.call_session_id)

        closed_at: None | str
        if isinstance(self.closed_at, datetime.datetime):
            closed_at = self.closed_at.isoformat()
        else:
            closed_at = self.closed_at

        conversation_id = str(self.conversation_id)

        created_at = self.created_at.isoformat()

        messages = []
        for messages_item_data in self.messages:
            messages_item = messages_item_data.to_dict()
            messages.append(messages_item)

        status = self.status.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "call_session_id": call_session_id,
                "closed_at": closed_at,
                "conversation_id": conversation_id,
                "created_at": created_at,
                "messages": messages,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.conversation_message_response import ConversationMessageResponse

        d = dict(src_dict)
        call_session_id = UUID(d.pop("call_session_id"))

        def _parse_closed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                closed_at_type_0 = datetime.datetime.fromisoformat(data)

                return closed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        closed_at = _parse_closed_at(d.pop("closed_at"))

        conversation_id = UUID(d.pop("conversation_id"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        messages = []
        _messages = d.pop("messages")
        for messages_item_data in _messages:
            messages_item = ConversationMessageResponse.from_dict(messages_item_data)

            messages.append(messages_item)

        status = ConversationPersistenceStatus(d.pop("status"))

        conversation_response = cls(
            call_session_id=call_session_id,
            closed_at=closed_at,
            conversation_id=conversation_id,
            created_at=created_at,
            messages=messages,
            status=status,
        )

        return conversation_response
