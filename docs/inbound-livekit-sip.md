# Inbound Telnyx calls through LiveKit SIP

Development remains Debug Chat only. `livekit-sip` is present only when the staging or production Compose overlay is selected.

## Architecture

```text
Telnyx PSTN call
  -> LiveKit SIP inbound trunk
  -> reusable individual dispatch rule
  -> isolated LiveKit room + SIP participant
  -> existing Voice Agent
  -> POST /internal/v1/calls/inbound-sip/claim
  -> Backend DID route + CallSession revision pins
  -> existing runtime-context, AgentSession, and call lifecycle
```

Backend routes only by the called DID. LiveKit trunk/rule IDs are diagnostics, not tenant authority. The claim uses `sip.callIDFull` when available and `sip.callID` as the fallback; database uniqueness on both identifiers makes retries converge.

## Environment topology

Start base Compose with the environment overlay:

```bash
docker compose --env-file infrastructure/compose/.env.staging \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.staging.yml config

docker compose --env-file infrastructure/compose/.env.prod \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.prod.yml config
```

`livekit-sip:v1.2.0` receives only the LiveKit API credentials/WS URL and Redis address. `LIVEKIT_SIP_REDIS_ADDRESS` must identify the same Redis used by the self-hosted LiveKit Server. Its native health endpoint listens on `LIVEKIT_SIP_HEALTH_PORT` inside the Compose network; Backend readiness does not depend on it.

## Configure a tenant DID

The tenant must be active and have published active TenantConfig, PromptSet, and VoiceRuntime revisions.

```bash
agentctl tenant inbound-route list <tenant-slug>
agentctl tenant inbound-route add <tenant-slug> +15550123456
agentctl tenant inbound-route remove <tenant-slug> +15550123456
```

## Provision LiveKit once

Copy the examples under `infrastructure/livekit/sip/`, replace the fake DID, verify the dispatch `agentName`, and run:

```bash
lk sip inbound create infrastructure/livekit/sip/inbound-trunk.telnyx.example.json
lk sip inbound list
lk sip dispatch create infrastructure/livekit/sip/dispatch-rule.example.json --trunks '<trunk-id>'
lk sip dispatch list
```

The trunk and dispatch rule are long-lived reusable objects. The `--trunks` value is the environment-specific ID returned when the inbound trunk is created.

## Configure Telnyx manually

1. Purchase or select the Telnyx number.
2. Create an inbound FQDN SIP connection pointing to the self-hosted LiveKit SIP endpoint.
3. Set both Telnyx Destination Number Format and Origination Number Format to `+E.164`; TCP is recommended by Telnyx/LiveKit guidance.
4. Associate the number with that connection.
5. Ensure the same `+E.164` DID appears in the LiveKit inbound trunk and Backend InboundRoute.

No Telnyx credential, API client, or automatic provisioning belongs in this repository slice.

## Real-number staging verification

1. Backend: verify the tenant is active; verify active Config, PromptSet, and VoiceRuntime; add the inbound route.
2. LiveKit: start/verify LiveKit Server, its shared Redis, LiveKit SIP, and the existing Voice Agent; create/verify the inbound trunk and trunk-scoped individual dispatch rule; verify `agentName`.
3. Telnyx: point the purchased DID to the LiveKit SIP endpoint and confirm `+E.164` destination/origination formats.
4. Call the real number.
5. Verify the path is Telnyx -> LiveKit SIP -> isolated room -> SIP participant -> Voice Agent -> Backend claim -> runtime-context -> greeting/conversation -> existing terminal lifecycle.
6. Inspect `GET /admin/v1/calls/<call-session-id>` and verify channel/provider, caller/called numbers, both available SIP IDs, trunk/rule IDs, room/participant identity, status, and all three pinned revisions.
7. Repeat/reconnect the agent job and verify the same SIP call returns the same CallSession.

## Deferred before real staging/production deployment

This Compose topology is not an Internet-ready SIP edge. Separately configure and verify public SIP signaling, RTP/media range, host/cloud firewall, NAT/public-IP behavior, provider source restrictions, DNS, TLS, Caddy for HTTP/WSS only, and production health/metrics monitoring. No SIP or RTP proxying through Caddy is intended.
