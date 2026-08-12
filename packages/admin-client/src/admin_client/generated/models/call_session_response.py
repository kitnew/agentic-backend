from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.call_channel import CallChannel
from ..models.call_direction import CallDirection
from ..models.call_session_status import CallSessionStatus

T = TypeVar("T", bound="CallSessionResponse")


@_attrs_define
class CallSessionResponse:
    """
    Attributes:
        called_phone_e164 (None | str):
        called_phone_raw (None | str):
        caller_phone_e164 (None | str):
        caller_phone_raw (None | str):
        channel (CallChannel):
        connected_at (datetime.datetime | None):
        created_at (datetime.datetime):
        direction (CallDirection):
        ended_at (datetime.datetime | None):
        failure_reason (None | str):
        handoff_destination (None | str):
        handoff_tool_call_id (None | str):
        id (UUID):
        livekit_participant_identity (None | str):
        prompt_set_revision_id (UUID):
        provider (str):
        provider_call_id (str):
        provider_dispatch_id (None | str):
        room_name (str):
        sip_call_id (None | str):
        sip_call_id_full (None | str):
        sip_dispatch_rule_id (None | str):
        sip_trunk_id (None | str):
        started_at (datetime.datetime | None):
        status (CallSessionStatus):
        tenant_config_revision_id (UUID):
        tenant_id (UUID):
        voice_runtime_revision_id (None | UUID):
    """

    called_phone_e164: None | str
    called_phone_raw: None | str
    caller_phone_e164: None | str
    caller_phone_raw: None | str
    channel: CallChannel
    connected_at: datetime.datetime | None
    created_at: datetime.datetime
    direction: CallDirection
    ended_at: datetime.datetime | None
    failure_reason: None | str
    handoff_destination: None | str
    handoff_tool_call_id: None | str
    id: UUID
    livekit_participant_identity: None | str
    prompt_set_revision_id: UUID
    provider: str
    provider_call_id: str
    provider_dispatch_id: None | str
    room_name: str
    sip_call_id: None | str
    sip_call_id_full: None | str
    sip_dispatch_rule_id: None | str
    sip_trunk_id: None | str
    started_at: datetime.datetime | None
    status: CallSessionStatus
    tenant_config_revision_id: UUID
    tenant_id: UUID
    voice_runtime_revision_id: None | UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        called_phone_e164: None | str
        called_phone_e164 = self.called_phone_e164

        called_phone_raw: None | str
        called_phone_raw = self.called_phone_raw

        caller_phone_e164: None | str
        caller_phone_e164 = self.caller_phone_e164

        caller_phone_raw: None | str
        caller_phone_raw = self.caller_phone_raw

        channel = self.channel.value

        connected_at: None | str
        if isinstance(self.connected_at, datetime.datetime):
            connected_at = self.connected_at.isoformat()
        else:
            connected_at = self.connected_at

        created_at = self.created_at.isoformat()

        direction = self.direction.value

        ended_at: None | str
        if isinstance(self.ended_at, datetime.datetime):
            ended_at = self.ended_at.isoformat()
        else:
            ended_at = self.ended_at

        failure_reason: None | str
        failure_reason = self.failure_reason

        handoff_destination: None | str
        handoff_destination = self.handoff_destination

        handoff_tool_call_id: None | str
        handoff_tool_call_id = self.handoff_tool_call_id

        id = str(self.id)

        livekit_participant_identity: None | str
        livekit_participant_identity = self.livekit_participant_identity

        prompt_set_revision_id = str(self.prompt_set_revision_id)

        provider = self.provider

        provider_call_id = self.provider_call_id

        provider_dispatch_id: None | str
        provider_dispatch_id = self.provider_dispatch_id

        room_name = self.room_name

        sip_call_id: None | str
        sip_call_id = self.sip_call_id

        sip_call_id_full: None | str
        sip_call_id_full = self.sip_call_id_full

        sip_dispatch_rule_id: None | str
        sip_dispatch_rule_id = self.sip_dispatch_rule_id

        sip_trunk_id: None | str
        sip_trunk_id = self.sip_trunk_id

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        status = self.status.value

        tenant_config_revision_id = str(self.tenant_config_revision_id)

        tenant_id = str(self.tenant_id)

        voice_runtime_revision_id: None | str
        if isinstance(self.voice_runtime_revision_id, UUID):
            voice_runtime_revision_id = str(self.voice_runtime_revision_id)
        else:
            voice_runtime_revision_id = self.voice_runtime_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "called_phone_e164": called_phone_e164,
                "called_phone_raw": called_phone_raw,
                "caller_phone_e164": caller_phone_e164,
                "caller_phone_raw": caller_phone_raw,
                "channel": channel,
                "connected_at": connected_at,
                "created_at": created_at,
                "direction": direction,
                "ended_at": ended_at,
                "failure_reason": failure_reason,
                "handoff_destination": handoff_destination,
                "handoff_tool_call_id": handoff_tool_call_id,
                "id": id,
                "livekit_participant_identity": livekit_participant_identity,
                "prompt_set_revision_id": prompt_set_revision_id,
                "provider": provider,
                "provider_call_id": provider_call_id,
                "provider_dispatch_id": provider_dispatch_id,
                "room_name": room_name,
                "sip_call_id": sip_call_id,
                "sip_call_id_full": sip_call_id_full,
                "sip_dispatch_rule_id": sip_dispatch_rule_id,
                "sip_trunk_id": sip_trunk_id,
                "started_at": started_at,
                "status": status,
                "tenant_config_revision_id": tenant_config_revision_id,
                "tenant_id": tenant_id,
                "voice_runtime_revision_id": voice_runtime_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_called_phone_e164(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        called_phone_e164 = _parse_called_phone_e164(d.pop("called_phone_e164"))

        def _parse_called_phone_raw(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        called_phone_raw = _parse_called_phone_raw(d.pop("called_phone_raw"))

        def _parse_caller_phone_e164(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        caller_phone_e164 = _parse_caller_phone_e164(d.pop("caller_phone_e164"))

        def _parse_caller_phone_raw(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        caller_phone_raw = _parse_caller_phone_raw(d.pop("caller_phone_raw"))

        channel = CallChannel(d.pop("channel"))

        def _parse_connected_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                connected_at_type_0 = datetime.datetime.fromisoformat(data)

                return connected_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        connected_at = _parse_connected_at(d.pop("connected_at"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        direction = CallDirection(d.pop("direction"))

        def _parse_ended_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                ended_at_type_0 = datetime.datetime.fromisoformat(data)

                return ended_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        ended_at = _parse_ended_at(d.pop("ended_at"))

        def _parse_failure_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        failure_reason = _parse_failure_reason(d.pop("failure_reason"))

        def _parse_handoff_destination(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        handoff_destination = _parse_handoff_destination(d.pop("handoff_destination"))

        def _parse_handoff_tool_call_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        handoff_tool_call_id = _parse_handoff_tool_call_id(
            d.pop("handoff_tool_call_id")
        )

        id = UUID(d.pop("id"))

        def _parse_livekit_participant_identity(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        livekit_participant_identity = _parse_livekit_participant_identity(
            d.pop("livekit_participant_identity")
        )

        prompt_set_revision_id = UUID(d.pop("prompt_set_revision_id"))

        provider = d.pop("provider")

        provider_call_id = d.pop("provider_call_id")

        def _parse_provider_dispatch_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        provider_dispatch_id = _parse_provider_dispatch_id(
            d.pop("provider_dispatch_id")
        )

        room_name = d.pop("room_name")

        def _parse_sip_call_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        sip_call_id = _parse_sip_call_id(d.pop("sip_call_id"))

        def _parse_sip_call_id_full(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        sip_call_id_full = _parse_sip_call_id_full(d.pop("sip_call_id_full"))

        def _parse_sip_dispatch_rule_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        sip_dispatch_rule_id = _parse_sip_dispatch_rule_id(
            d.pop("sip_dispatch_rule_id")
        )

        def _parse_sip_trunk_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        sip_trunk_id = _parse_sip_trunk_id(d.pop("sip_trunk_id"))

        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = datetime.datetime.fromisoformat(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))

        status = CallSessionStatus(d.pop("status"))

        tenant_config_revision_id = UUID(d.pop("tenant_config_revision_id"))

        tenant_id = UUID(d.pop("tenant_id"))

        def _parse_voice_runtime_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                voice_runtime_revision_id_type_0 = UUID(data)

                return voice_runtime_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        voice_runtime_revision_id = _parse_voice_runtime_revision_id(
            d.pop("voice_runtime_revision_id")
        )

        call_session_response = cls(
            called_phone_e164=called_phone_e164,
            called_phone_raw=called_phone_raw,
            caller_phone_e164=caller_phone_e164,
            caller_phone_raw=caller_phone_raw,
            channel=channel,
            connected_at=connected_at,
            created_at=created_at,
            direction=direction,
            ended_at=ended_at,
            failure_reason=failure_reason,
            handoff_destination=handoff_destination,
            handoff_tool_call_id=handoff_tool_call_id,
            id=id,
            livekit_participant_identity=livekit_participant_identity,
            prompt_set_revision_id=prompt_set_revision_id,
            provider=provider,
            provider_call_id=provider_call_id,
            provider_dispatch_id=provider_dispatch_id,
            room_name=room_name,
            sip_call_id=sip_call_id,
            sip_call_id_full=sip_call_id_full,
            sip_dispatch_rule_id=sip_dispatch_rule_id,
            sip_trunk_id=sip_trunk_id,
            started_at=started_at,
            status=status,
            tenant_config_revision_id=tenant_config_revision_id,
            tenant_id=tenant_id,
            voice_runtime_revision_id=voice_runtime_revision_id,
        )

        call_session_response.additional_properties = d
        return call_session_response

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
