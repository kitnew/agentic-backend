# LiveKit SIP provisioning templates

Replace the example DID and verify `agentName` matches `LIVEKIT_AGENT_NAME`, then create the reusable resources once:

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

Set the reusable outbound trunk ID returned by the final command as
`LIVEKIT_SIP_OUTBOUND_TRUNK_ID`. Backend uses it only to dial a configured human
handoff destination into the caller's existing room. Keep Telnyx credentials out
of the JSON template and repository.
