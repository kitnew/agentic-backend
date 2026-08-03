# Human handoff operations

Human handoff is an opt-in inbound-SIP feature. The runtime does not use SIP
REFER. When the caller explicitly asks for a person, the voice agent creates a
second SIP participant in the current room through LiveKit. The agent then
shuts down its `AgentSession`, while the caller and employee remain connected.

Official references: [LiveKit outbound calls](https://docs.livekit.io/telephony/making-calls/outbound-calls/),
[LiveKit SIP API](https://docs.livekit.io/reference/telephony/sip-api/),
[LiveKit Telnyx setup](https://docs.livekit.io/telephony/start/providers/telnyx/),
and [Telnyx LiveKit configuration](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide).

If either SIP participant leaves after handoff, the runtime deletes the room.
This ends the remaining SIP leg and finalizes the existing call session.

## Tenant configuration

Handoff is configured independently for every tenant. Keep it disabled until
the external trunk is ready:

```yaml
voice:
  enabled: true
  handoff: false
  inbound_dids:
    - "+421552301299"
  outbound_dids: []
  outbound_trunk_id: ""
```

For an enabled tenant, set exactly one destination for the current minimal
handoff flow:

```yaml
voice:
  enabled: true
  handoff: true
  outbound_dids:
    - "+421900111222"
  outbound_trunk_id: "ST_..."
```

`outbound_dids` contains the employee's destination in E.164-compatible form.
`outbound_trunk_id` is the stored LiveKit outbound trunk ID, not the Telnyx
connection ID. The application normalizes the number and copies these values
into the signed LiveKit job metadata; no handoff routing values are read from
`.env`.

## Server prerequisites

The production Compose override already contains a separate `livekit-sip`
service. On the deployment host:

1. Set a real `LIVEKIT_SIP_DOMAIN` A record to `LIVEKIT_SIP_EXTERNAL_IP`.
2. Allow TCP and UDP `LIVEKIT_SIP_PORT` (normally `5060`).
3. Allow UDP `LIVEKIT_SIP_RTP_PORT_START` through `LIVEKIT_SIP_RTP_PORT_END`
   (normally `10000-20000`).
4. Keep `LIVEKIT_SIP_HEALTH_PORT` private.
5. Keep `LIVEKIT_INTERNAL_URL=ws://livekit:7880` and use the existing Redis
   bridge values from `.env.production`.

`livekit-sip` uses host networking and advertises
`LIVEKIT_SIP_EXTERNAL_IP` in SDP. Caddy does not proxy SIP or RTP.

Validate the deployment input before starting services:

```bash
ENV_FILE=.env.production ./deploy/deploy.sh --check
```

## Telnyx setup

Telnyx requires a paid account for this integration.

1. Purchase or select the DID used for inbound calls.
2. In Telnyx Mission Control, create an FQDN SIP connection.
3. Add the public LiveKit SIP host and port as the FQDN destination:
   `LIVEKIT_SIP_DOMAIN:LIVEKIT_SIP_PORT`.
4. Use TCP for SIP signaling unless the carrier setup requires UDP.
5. Set inbound and origination number format to `+E.164`.
6. Configure Telnyx outbound authentication with a username and password.
7. Create or select an outbound voice profile and associate the DID with the
   connection.

The same Telnyx connection may carry inbound and outbound traffic. Do not put
Telnyx credentials in this repository. Store them only in the LiveKit outbound
trunk configuration or the protected deployment secret store.

## LiveKit outbound trunk

Create one stored outbound trunk in the LiveKit project. Do not create a trunk
per call. The exact CLI payload depends on the installed LiveKit CLI, but the
required values are:

```json
{
  "trunk": {
    "name": "Telnyx human handoff",
    "address": "sip.telnyx.com",
    "numbers": ["<Telnyx DID in E.164>"],
    "authUsername": "<Telnyx SIP username>",
    "authPassword": "<Telnyx SIP password>",
    "headers_to_attributes": {
      "X-Telnyx-Username": "<Telnyx SIP username>"
    }
  }
}
```

Create it with the LiveKit CLI or Server API, then put the returned `ST_...`
ID into the tenant's `voice.outbound_trunk_id`. The application supplies the
employee number per call; the trunk supplies the Telnyx authentication and
caller ID.

The existing inbound trunk and dispatch rule remain required. Follow
[`inbound-livekit-sip.md`](inbound-livekit-sip.md) for their setup and DID
routing.

## Smoke test

After deployment:

```bash
docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml --profile sip ps

docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml --profile sip \
  logs --tail=200 livekit-sip livekit voice-agent api
```

Place an inbound call and explicitly ask for a human. Verify that:

1. The employee's phone rings.
2. LiveKit shows two SIP participants in the original room.
3. The agent stops generating speech after the employee answers.
4. `voice-agent` logs `human_handoff_started`.
5. Hanging up either the employee or the caller ends the remaining leg.
6. Backend Core finalizes the call once.

Static Compose and deployment checks do not prove a real call. The final gate
is a real inbound call through Telnyx with server logs and participant state.

The current runtime supports one outbound destination per enabled tenant. It
does not yet choose among multiple `outbound_dids`, perform warm handoff, or
pass extra context to the employee. The runtime adds a temporary instruction
when the feature is enabled so old tenant text saying that transfer is
unavailable does not block the tool.
