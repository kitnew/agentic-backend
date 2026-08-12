from datetime import timedelta

from livekit import api
from livekit.protocol import agent_dispatch
from livekit.protocol import room as room_proto


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
