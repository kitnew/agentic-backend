from dataclasses import dataclass
from datetime import timedelta

from livekit import api
from livekit.protocol import agent_dispatch
from livekit.protocol import room as room_proto


@dataclass(frozen=True)
class EgressResult:
    egress_id: str
    room_name: str
    status: str
    filename: str | None = None
    size: int | None = None
    duration_ns: int | None = None
    started_at_ns: int | None = None
    ended_at_ns: int | None = None
    error: str | None = None
    requested_filepath: str | None = None


class LiveKitAdapter:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        api_secret: str,
        participant_token_ttl_seconds: int,
        sip_outbound_trunk_id: str | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._participant_token_ttl_seconds = participant_token_ttl_seconds
        self._sip_outbound_trunk_id = sip_outbound_trunk_id
        self._client: api.LiveKitAPI | None = None

    @property
    def client(self) -> api.LiveKitAPI:
        if self._client is None:
            self._client = api.LiveKitAPI(
                self._url,
                self._api_key,
                self._api_secret,
            )
        return self._client

    async def start(self) -> None:
        _ = self.client

    async def create_dispatch(
        self,
        *,
        agent_name: str,
        room_name: str,
        metadata: str,
    ) -> str:
        dispatch = await self.client.agent_dispatch.create_dispatch(
            agent_dispatch.CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=room_name,
                metadata=metadata,
            )
        )
        return dispatch.id

    async def delete_dispatch(self, dispatch_id: str, room_name: str) -> None:
        await self.client.agent_dispatch.delete_dispatch(dispatch_id, room_name)

    async def delete_room(self, room_name: str) -> None:
        await self.client.room.delete_room(room_proto.DeleteRoomRequest(room=room_name))

    async def room_exists(self, room_name: str) -> bool:
        response = await self.client.room.list_rooms(
            room_proto.ListRoomsRequest(names=[room_name])
        )
        return any(room.name == room_name for room in response.rooms)

    async def start_call_recording(
        self, *, room_name: str, storage_key: str
    ) -> EgressResult:
        info = await self.client.egress.start_room_composite_egress(
            api.RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.MP3,
                        filepath=storage_key,
                        disable_manifest=True,
                    )
                ],
            )
        )
        return self.egress_result(info)

    async def get_egress(self, egress_id: str) -> EgressResult | None:
        response = await self.client.egress.list_egress(
            api.ListEgressRequest(egress_id=egress_id)
        )
        return self.egress_result(response.items[0]) if response.items else None

    async def find_egress(
        self, *, room_name: str, storage_key: str
    ) -> EgressResult | None:
        response = await self.client.egress.list_egress(
            api.ListEgressRequest(room_name=room_name)
        )
        return next(
            (
                result
                for item in response.items
                if (result := self.egress_result(item)).requested_filepath
                == storage_key
            ),
            None,
        )

    @staticmethod
    def egress_result(info: api.EgressInfo) -> EgressResult:
        file = info.file_results[0] if info.file_results else None
        requested = (
            info.room_composite.file_outputs[0].filepath
            if info.HasField("room_composite")
            and info.room_composite.file_outputs
            else None
        )
        return EgressResult(
            egress_id=info.egress_id,
            room_name=info.room_name,
            status=api.EgressStatus.Name(info.status)
            .removeprefix("EGRESS_")
            .lower(),
            filename=file.filename if file else None,
            size=file.size if file else None,
            duration_ns=file.duration if file else None,
            started_at_ns=file.started_at if file else None,
            ended_at_ns=file.ended_at if file else None,
            error=(info.error or None),
            requested_filepath=requested,
        )

    async def create_sip_participant(
        self, *, room_name: str, participant_identity: str, phone_number: str
    ) -> tuple[str, str]:
        if self._sip_outbound_trunk_id is None:
            raise RuntimeError("LiveKit SIP outbound trunk is not configured")
        participant = await self.client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room_name,
                participant_identity=participant_identity,
                sip_call_to=phone_number,
                sip_trunk_id=self._sip_outbound_trunk_id,
                wait_until_answered=True,
                hide_phone_number=True,
            )
        )
        return participant.participant_identity, participant.sip_call_id

    def issue_participant_token(self, *, room_name: str, identity: str) -> str:
        grants = api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=False,
            can_publish_sources=["microphone"],
        )
        return (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(identity)
            .with_ttl(timedelta(seconds=self._participant_token_ttl_seconds))
            .with_grants(grants)
            .to_jwt()
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
