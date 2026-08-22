from dataclasses import dataclass
from datetime import timedelta

import aiohttp
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
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._participant_token_ttl_seconds = participant_token_ttl_seconds
        self._client: api.LiveKitAPI | None = None
        self._session: aiohttp.ClientSession | None = None
        self._trace_config: aiohttp.TraceConfig | None = None

    def instrument_http(
        self,
        tracer_provider: object,
        meter_provider: object,
    ) -> None:
        if self._client is not None:
            raise RuntimeError("LiveKit telemetry must be configured before start")
        from opentelemetry.instrumentation.aiohttp_client import create_trace_config

        self._trace_config = create_trace_config(
            tracer_provider=tracer_provider,  # type: ignore[arg-type]
            meter_provider=meter_provider,  # type: ignore[arg-type]
        )

    @property
    def client(self) -> api.LiveKitAPI:
        if self._client is None:
            if self._trace_config is not None:
                self._session = aiohttp.ClientSession(
                    trace_configs=[self._trace_config]
                )
            self._client = api.LiveKitAPI(
                self._url,
                self._api_key,
                self._api_secret,
                session=self._session,
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
            if info.HasField("room_composite") and info.room_composite.file_outputs
            else None
        )
        return EgressResult(
            egress_id=info.egress_id,
            room_name=info.room_name,
            status=api.EgressStatus.Name(info.status).removeprefix("EGRESS_").lower(),
            filename=file.filename if file else None,
            size=file.size if file else None,
            duration_ns=file.duration if file else None,
            started_at_ns=file.started_at if file else None,
            ended_at_ns=file.ended_at if file else None,
            error=(info.error or None),
            requested_filepath=requested,
        )

    async def create_sip_participant(
        self,
        *,
        room_name: str,
        participant_identity: str,
        phone_number: str,
        caller_number: str,
        outbound_trunk_id: str,
    ) -> tuple[str, str]:
        participant = await self.client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room_name,
                participant_identity=participant_identity,
                sip_call_to=phone_number,
                sip_number=caller_number,
                sip_trunk_id=outbound_trunk_id,
                wait_until_answered=True,
                hide_phone_number=True,
            )
        )
        return participant.participant_identity, participant.sip_call_id

    async def reconcile_shared_sip(
        self,
        *,
        numbers: list[str],
        provider_address: str,
        provider_username: str | None,
        provider_password: str | None,
        agent_name: str,
        inbound_trunk_id: str | None,
        outbound_trunk_id: str | None,
        dispatch_rule_id: str | None,
    ) -> tuple[str, str, str]:
        inbound = await self.client.sip.list_sip_inbound_trunk(
            api.ListSIPInboundTrunkRequest(
                trunk_ids=[inbound_trunk_id] if inbound_trunk_id else []
            )
        )
        inbound_item = next(
            (
                item
                for item in inbound.items
                if inbound_trunk_id or item.name == "Agent Platform shared inbound"
            ),
            None,
        )
        if inbound_item is None:
            inbound_item = await self.client.sip.create_sip_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name="Agent Platform shared inbound", numbers=numbers
                    )
                )
            )
        elif list(inbound_item.numbers) != numbers:
            inbound_item = await self.client.sip.update_sip_inbound_trunk_fields(
                inbound_item.sip_trunk_id, numbers=numbers
            )

        outbound = await self.client.sip.list_sip_outbound_trunk(
            api.ListSIPOutboundTrunkRequest(
                trunk_ids=[outbound_trunk_id] if outbound_trunk_id else []
            )
        )
        outbound_item = next(
            (
                item
                for item in outbound.items
                if outbound_trunk_id or item.name == "Agent Platform shared outbound"
            ),
            None,
        )
        if outbound_item is None:
            outbound_item = await self.client.sip.create_sip_outbound_trunk(
                api.CreateSIPOutboundTrunkRequest(
                    trunk=api.SIPOutboundTrunkInfo(
                        name="Agent Platform shared outbound",
                        address=provider_address,
                        numbers=numbers,
                        auth_username=provider_username or "",
                        auth_password=provider_password or "",
                    )
                )
            )
        else:
            outbound_item = await self.client.sip.update_sip_outbound_trunk_fields(
                outbound_item.sip_trunk_id,
                address=provider_address,
                numbers=numbers,
                auth_username=provider_username,
                auth_password=provider_password,
            )

        dispatch = await self.client.sip.list_sip_dispatch_rule(
            api.ListSIPDispatchRuleRequest(
                dispatch_rule_ids=[dispatch_rule_id] if dispatch_rule_id else []
            )
        )
        dispatch_item = next(
            (
                item
                for item in dispatch.items
                if dispatch_rule_id or item.name == "Agent Platform shared dispatch"
            ),
            None,
        )
        if dispatch_item is None:
            dispatch_item = await self.client.sip.create_sip_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    name="Agent Platform shared dispatch",
                    trunk_ids=[inbound_item.sip_trunk_id],
                    rule=api.SIPDispatchRule(
                        dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                            room_prefix="sip-call-"
                        )
                    ),
                    room_config=api.RoomConfiguration(
                        agents=[api.RoomAgentDispatch(agent_name=agent_name)]
                    ),
                )
            )
        elif list(dispatch_item.trunk_ids) != [inbound_item.sip_trunk_id]:
            dispatch_item = await self.client.sip.update_sip_dispatch_rule_fields(
                dispatch_item.sip_dispatch_rule_id,
                trunk_ids=[inbound_item.sip_trunk_id],
            )
        return (
            inbound_item.sip_trunk_id,
            outbound_item.sip_trunk_id,
            dispatch_item.sip_dispatch_rule_id,
        )

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
        if self._session is not None:
            await self._session.close()
