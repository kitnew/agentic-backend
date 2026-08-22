# Legacy LiveKit SIP provisioning templates

These files are migration/emergency diagnostics only. Normal provisioning is owned by Platform → Telephony.

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
