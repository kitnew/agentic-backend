from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CreateTestVoiceSessionResponse")


@_attrs_define
class CreateTestVoiceSessionResponse:
    """
    Attributes:
        call_session_id (UUID):
        livekit_url (str):
        participant_identity (str):
        participant_token (str):
        room_name (str):
    """

    call_session_id: UUID
    livekit_url: str
    participant_identity: str
    participant_token: str
    room_name: str

    def to_dict(self) -> dict[str, Any]:
        call_session_id = str(self.call_session_id)

        livekit_url = self.livekit_url

        participant_identity = self.participant_identity

        participant_token = self.participant_token

        room_name = self.room_name

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "call_session_id": call_session_id,
                "livekit_url": livekit_url,
                "participant_identity": participant_identity,
                "participant_token": participant_token,
                "room_name": room_name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        call_session_id = UUID(d.pop("call_session_id"))

        livekit_url = d.pop("livekit_url")

        participant_identity = d.pop("participant_identity")

        participant_token = d.pop("participant_token")

        room_name = d.pop("room_name")

        create_test_voice_session_response = cls(
            call_session_id=call_session_id,
            livekit_url=livekit_url,
            participant_identity=participant_identity,
            participant_token=participant_token,
            room_name=room_name,
        )

        return create_test_voice_session_response
