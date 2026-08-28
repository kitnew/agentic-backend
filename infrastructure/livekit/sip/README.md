# Legacy LiveKit SIP provisioning templates

These files are migration/emergency diagnostics only. Normal provisioning is
owned by Backend Platform → Telephony reconciliation after tenant Publish.

The `lk sip` commands below call the LiveKit API directly. They do not use
Backend credentials or the tenant `agentctl` lifecycle. The CLI must have a
LiveKit project configured whose URL, API key, and API secret all belong to the
same deployment. Check the selected project with `lk project list` before
running a diagnostic command.

```bash
lk sip inbound create infrastructure/livekit/sip/inbound-trunk.telnyx.example.json
lk sip inbound list
lk sip dispatch create infrastructure/livekit/sip/dispatch-rule.example.json --trunks '<trunk-id>'
lk sip dispatch list
lk sip outbound create infrastructure/livekit/sip/outbound-trunk.telnyx.example.json \
  --auth-user "$SIP_AUTH_USERNAME" \
  --auth-pass "$SIP_AUTH_PASSWORD"
```

The dispatch rule is individual-call routing: each inbound caller gets an isolated `sip-call-...` room. Do not create trunks or rules per call. See `docs/inbound-livekit-sip.md` for Telnyx and deployment steps.

Do not copy returned resource IDs into `.env`; the Backend stores them as platform provisioning state.

An HTTP 401/Twirp `Unauthenticated` response means the selected LiveKit CLI
project was not accepted by the LiveKit endpoint. It is an API-authentication
problem, not a Telnyx SIP-credential problem. For LiveKit Cloud, re-link the
project with `lk cloud auth`; for self-hosted LiveKit, add the deployment with
`lk project add` using the matching URL, API key, and API secret.
