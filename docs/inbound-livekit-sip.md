# Inbound LiveKit SIP operations

Inbound telephony is an opt-in staging/production path:

```text
Telnyx -> livekit-sip -> LiveKit Server -> SIP room participant
       -> voice-agent -> Backend Core bootstrap -> existing AgentSession/finalization
```

Local `docker-compose.yml` has no SIP service. The production override defines
`livekit-sip` under the `sip` profile; `deploy/deploy.sh` activates that profile only
when `INBOUND_SIP_ENABLED=true`.

For outbound human handoff from an inbound call, see
[`human-handoff.md`](human-handoff.md).

## Configuration

Set these in the staging or production environment:

| Variable | Purpose |
|---|---|
| `INBOUND_SIP_ENABLED` | Enables Backend Core routing and the deployment script's SIP profile |
| `LIVEKIT_SIP_IMAGE` | Pinned official image, currently `livekit/sip:v1.7.0` |
| `LIVEKIT_SIP_DOMAIN` | Public SIP DNS name |
| `LIVEKIT_SIP_EXTERNAL_IP` | Public IPv4 advertised in SIP/SDP |
| `LIVEKIT_SIP_INTERNAL_URL` | Host-reachable LiveKit URL, normally `ws://127.0.0.1:7880` |
| `LIVEKIT_SIP_REDIS_ADDRESS` | Host-reachable Redis address, normally `127.0.0.1:6379` |
| `LIVEKIT_SIP_HEALTH_PORT` | SIP health port, default `8082` |
| `LIVEKIT_SIP_PORT` | Public TCP/UDP signalling port |
| `LIVEKIT_SIP_RTP_PORT_START`, `LIVEKIT_SIP_RTP_PORT_END` | Public UDP RTP range |
| `LIVEKIT_REDIS_ADDRESS` | Bridge address used by LiveKit Server |
| `LIVEKIT_INTERNAL_URL` | Bridge address used by API and voice-agent containers |
| `LIVEKIT_SIP_EXPECTED_TRUNK_ID` | Optional Backend Core allow-check after the trunk exists |
| `LIVEKIT_SIP_EXPECTED_RULE_ID` | Optional Backend Core allow-check after the rule exists |
| `VOICE_SESSION_TOKEN_SECRET` | Existing voice-agent service-auth signing secret |
| `LIVEKIT_BACKEND_TOKEN_TTL_SECONDS` | Existing short-lived backend token lifetime |

The SIP container receives the existing `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`.
Do not create a second LiveKit credential pair, Redis instance, or Redis credentials.

`livekit-sip` uses host networking. LiveKit port `7880` and Redis port `6379` are
published to `127.0.0.1` only so SIP can reach them without exposing either service
publicly. The application containers keep using `ws://livekit:7880` and
`redis:6379` over the Compose bridge. SIP signalling and RTP use the host network
directly; there is no Docker `ports` mapping for either range.

Map each inbound DID in exactly one enabled tenant YAML:

```yaml
voice:
  enabled: true
  inbound_dids:
    - "<E.164 DID supplied later>"
```

Backend Core normalizes numbers before matching. Startup rejects duplicate DID
assignments. Enabling SIP with no DID, an invalid environment, or incomplete network
settings fails validation.

Idempotency uses `sip.callIDFull` when present because it is the carrier's globally
unique call ID. Older/misconfigured participants fall back to LiveKit's `sip.callID`;
the stored key prefixes the source so the two ID namespaces cannot collide.

`sip.makmanagency.com` is the public DNS name for the SIP service. Its A record must
resolve to `LIVEKIT_SIP_EXTERNAL_IP`; Telnyx targets that host on `LIVEKIT_SIP_PORT`.
Caddy does not proxy SIP or RTP. Open the signalling port on both TCP and UDP and the
entire configured RTP range on UDP. Keep the health port private in the host firewall.

## Manual work still required

Nothing in this repository provisions carrier or LiveKit telephony resources. After
deployment configuration is ready:

1. Create the Telnyx Connection and point it at `sip.makmanagency.com:<SIP port>`.
2. Assign the real Telnyx DID to that Connection.
3. Create the LiveKit inbound trunk with the real number and carrier restrictions.
4. Create a LiveKit dispatch rule targeting `LIVEKIT_AGENT_NAME`.
5. Put the real DID in one tenant's `voice.inbound_dids`.
6. Optionally set the resulting trunk/rule IDs as expected-ID checks.
7. Configure DNS and firewall rules, then enable SIP and deploy.

Do not commit the DID, carrier credentials, trunk credentials, or production IDs to the
example files.

## Verify and smoke test

Validate without starting containers:

```bash
ENV_FILE=.env.production ./deploy/deploy.sh --check
```

After deployment:

```bash
docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml --profile sip ps
docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml --profile sip \
  logs --tail=200 livekit-sip livekit redis voice-agent api
```

Confirm `livekit-sip`, `livekit`, and `redis` are healthy and the SIP logs show no
LiveKit or Redis connection errors. Place one call to the configured DID, then:

1. List the room and participant with LiveKit CLI.
2. Confirm participant kind `SIP` and attributes `sip.callIDFull`, `sip.callID`,
   `sip.trunkPhoneNumber`, `sip.trunkID`, and `sip.ruleID`.
3. Confirm logs contain `sip_participant_discovered`, `inbound_tenant_resolved`,
   one `inbound_call_session_created` (or `reused` on retry),
   `agent_session_started`, and `sip_call_finalized` with matching correlation IDs.
4. Confirm one `call_sessions` row reaches the normal terminal/finalization state and
   its transcript/messages use the existing persistence path.
5. Retry the bootstrap or repeat the same dispatched job and confirm the same
   `call_session_id` is returned.

To disable inbound calls, set `INBOUND_SIP_ENABLED=false` and redeploy. The SIP profile
is omitted; Browser/Debug Chat `/api/v1/voice/livekit/sessions` remains unchanged.
