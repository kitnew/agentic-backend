# Tenant Telephony and LiveKit SIP

Tenant Telephony is canonical Backend state for the tenant phone number. The
tenant Agent component owns human-handoff destinations. Operators never
configure LiveKit resource IDs or separate inbound routes.

## Operator workflow through `agentctl`

Handoff is authored in the tenant workspace, inside `tenant.yaml`:

```yaml
handoff:
  destinations:
    reception:
      description: Reservations desk
      phone_number: "+421900000001"
```

Validate and save that Agent draft with the normal workspace lifecycle:

```bash
agentctl plan tenant penzion-grand
agentctl push tenant penzion-grand
```

The tenant DID is a remote-only Telephony draft and has its own operational
facade:

```bash
agentctl did show penzion-grand
agentctl did assign penzion-grand +421551234567
agentctl did remove penzion-grand
```

`did assign` and `did remove` plan and save a Telephony draft; they do not
publish it. `did show` reports the draft and published DID, publication, phone
claim, and provisioning state. Activate Agent and Telephony changes together:

```bash
agentctl publish tenant penzion-grand
```

There is no current `agentctl tenant telephony ...` or
`agentctl tenant config publish ...` command. Telephony has no local workspace
file; the aggregate tenant publish includes its remote draft.

Publish commits the desired state and schedules automatic reconciliation. The
control plane then reports readiness or a degraded/error state. **Platform →
Telephony → Repair** is only for an explicit retry/diagnostic action.

The published phone number is both the inbound DID and outbound handoff caller
ID. Inbound calls resolve only from `sip.trunkPhoneNumber`; caller number is
never used for tenant routing. Handoff phone numbers are not exposed to the
model.

## Platform bootstrap

Set deployment credentials/settings only:

```dotenv
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LIVEKIT_AGENT_NAME=hospitality-voice-agent
SIP_PROVIDER_ADDRESS=sip.telnyx.com
SIP_PROVIDER_USERNAME=...
SIP_PROVIDER_PASSWORD=...
```

Normal provisioning is automatic after tenant Publish. Backend creates or
updates one shared inbound trunk, outbound trunk, and shared dispatch rule,
stores their external IDs in PostgreSQL, and synchronizes the exact set of
phone numbers from active published tenants. The inbound trunk uses an
explicit numbers list (not a wildcard); add/change/remove/disable operations
reconcile that list, and Backend still routes DID fail-closed from canonical
published state. Reconciliation is idempotent and retry-safe.

Open **Platform → Telephony** and use **Repair** only when an explicit retry or
diagnostic action is needed.

`infrastructure/livekit/sip/*.json` and `lk sip ...` are legacy/emergency
diagnostics, not the normal provisioning workflow. `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`
and `agentctl tenant inbound-route` are removed.

## Remaining provider-side prerequisite

The control plane does not purchase numbers or configure Telnyx connections. The outbound Telnyx connection uses credential authentication, so keep the username and password in the deployment env file. Inbound routing uses the Telnyx Primary FQDN and the deployed LiveKit SIP endpoint. The operator must still purchase/select the number, enable outbound calling, and use E.164 formats.

After that provider-side prerequisite, tenant onboarding uses the tenant
workspace for Agent/handoff, `agentctl did` for the DID, and the aggregate
tenant Publish command.

## Runtime path

```text
sip.trunkPhoneNumber
  → tenant_telephony.phone_number
  → phone claim and shared LiveKit inbound trunk
  → published release/runtime bundle
  → CallSession release and bundle pins
  → Voice Agent

handoff semantic key
  → RuntimeTelephony.handoff_destinations
  → pinned destination phone number
  → platform_telephony.outbound_trunk_id
  → CreateSIPParticipant(
       sip_number=destination phone number,
       caller_number=tenant phone number
    )
```

Unknown or malformed DIDs, unavailable tenants, missing SIP attributes, and unavailable outbound infrastructure fail closed. Raw phone numbers are not metric labels; external IDs appear only in expandable platform diagnostics.
