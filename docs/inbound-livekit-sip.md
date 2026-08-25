# Tenant Telephony and LiveKit SIP

Tenant Telephony is canonical Backend state. Operators never configure LiveKit resource IDs or separate inbound routes.

## Operator workflow

1. Create the tenant and its normal configuration.
2. Open **Tenant → Telephony**.
3. Set one E.164 phone number.
4. Add semantic human-handoff destinations.
5. Save and Publish.
6. Publish commits the desired state and schedules automatic reconciliation; the control plane then reports readiness or a degraded/error state. **Platform → Telephony → Repair** is only for an explicit retry/diagnostic action.

The same workflow is available through `agentctl tenant telephony show`, `set-number`, `handoff set`, `handoff remove`, and `status`. CLI changes use the existing TenantConfig draft and publish lifecycle.

```bash
agentctl tenant telephony set-number penzion-grand +421551234567
agentctl tenant telephony handoff set penzion-grand reception +421900000001
agentctl tenant config publish penzion-grand
agentctl tenant telephony status penzion-grand
```

The published phone number is both the inbound DID and outbound handoff caller ID. Inbound calls resolve only from `sip.trunkPhoneNumber`; caller number is never used for tenant routing. Handoff phone numbers are not exposed to the model.

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

Open **Platform → Telephony** and use **Repair**. Backend creates or updates one shared inbound trunk, outbound trunk, and shared dispatch rule, stores their external IDs in PostgreSQL, and synchronizes the exact set of phone numbers from active published tenants. The inbound trunk uses an explicit numbers list (not a wildcard); add/change/remove/disable operations reconcile that list, and Backend still routes DID fail-closed from canonical published state. Reconciliation is idempotent and retry-safe.

`infrastructure/livekit/sip/*.json` and `lk sip ...` are legacy/emergency diagnostics. `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` and `agentctl tenant inbound-route` are removed.

## Remaining provider-side prerequisite

The control plane does not purchase numbers or configure Telnyx connections. The outbound Telnyx connection uses credential authentication, so keep the username and password in the deployment env file. Inbound routing uses the Telnyx Primary FQDN and the deployed LiveKit SIP endpoint. The operator must still purchase/select the number, enable outbound calling, and use E.164 formats.

After that provider-side prerequisite, tenant onboarding is entirely **Tenant → Telephony**.

## Runtime path

```text
sip.trunkPhoneNumber
  → tenant_telephony.phone_number
  → published TenantConfig revision
  → CallSession revision pins
  → Voice Agent

handoff semantic key
  → pinned Tenant Telephony destination
  → platform_telephony.outbound_trunk_id
  → CreateSIPParticipant(sip_number=tenant phone number)
```

Unknown or malformed DIDs, unavailable tenants, missing SIP attributes, and unavailable outbound infrastructure fail closed. Raw phone numbers are not metric labels; external IDs appear only in expandable platform diagnostics.
