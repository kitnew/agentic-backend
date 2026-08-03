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
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._participant_token_ttl_seconds = participant_token_ttl_seconds
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
