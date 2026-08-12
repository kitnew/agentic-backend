# LiveKit SIP provisioning templates

Replace the example DID and verify `agentName` matches `LIVEKIT_AGENT_NAME`, then create the reusable resources once:

```bash
lk sip inbound create infrastructure/livekit/sip/inbound-trunk.telnyx.example.json
lk sip inbound list
lk sip dispatch create infrastructure/livekit/sip/dispatch-rule.example.json --trunks '<trunk-id>'
lk sip dispatch list
```

The dispatch rule is individual-call routing: each inbound caller gets an isolated `sip-call-...` room. Do not create trunks or rules per call. See `docs/inbound-livekit-sip.md` for Telnyx and deployment steps.
