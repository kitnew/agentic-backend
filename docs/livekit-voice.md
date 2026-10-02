# LiveKit voice deployment notes

## Per-call AI usage

LiveKit Agents 1.8.2 emits `session_usage_updated` cumulative snapshots. The Voice
Agent sends the latest snapshot at most once every five seconds and flushes it
before call terminalization. All three session modes use the same collector:
cascade LLM/STT/TTS; realtime model and its standalone transcript STT; and
half-cascade realtime model, standalone transcript STT, and ElevenLabs TTS.
The standalone STT is the session's `stt` instance even when its transcript is
only a sidecar, so its plugin metrics enter LiveKit's session usage collector.
No plugin usage event is counted a second time for persistence. Soniox STT
streams include the call UUID as `client_reference_id` through the pinned
plugin's supported option.

Backend owns `call_ai_usage`: one row per call, provider, service, model, and
LiveKit source, with raw cumulative counters in JSONB. The authenticated
`PUT /internal/v1/calls/{call_id}/ai-usage` checks the call exists, derives its
tenant from the call, and replaces only older observations. Voice reporting is
best effort and has a two-second HTTP timeout; failures never fail the call.
The call terminalizer makes a final attempt before its existing completion
observation. A process crash can lose up to the pending debounce interval;
the last persisted snapshot remains available. PostgreSQL is authoritative.

`estimated_cost_usd` is a local **estimate**, and `provider_cost_usd` is reserved
for **provider-reconciled** money. Both are nullable NUMERIC. Raw usage remains
available when prices are unknown. Set Backend `AI_USAGE_PRICES` to an explicit
JSON object keyed `provider/service/model`, for example:

```json
{"openai/llm/example-model":{"source":"provider-rate-sheet-YYYY-MM-DD","rates":{"input_tokens":"<USD per uncached token>","input_cached_tokens":"<USD per cached token>","output_tokens":"<USD per output token>"}}}
```

Replace placeholders with verified rates before enabling an estimate. Rates
are USD **per one unit**, Decimal strings. For LLM, `input_tokens` includes
cached tokens; the calculator subtracts cached input before applying the
regular input rate. Any nonzero unpriced billed dimension leaves the estimate
NULL. For STT, keys can include `audio_duration`, `input_tokens`, and
`output_tokens`; for TTS, `characters_count`, `audio_duration`, `input_tokens`,
and `output_tokens`. Explicit zero rates are required for measured dimensions
that a provider does not bill. No prices are configured by default.

The Backend publishes `voice_ai_usage_tokens_total`,
`voice_ai_usage_seconds_total`, `voice_ai_usage_characters_total`, and
`voice_ai_usage_estimated_cost_usd_total` from accepted increases. The Voice
Agent publishes `voice_usage_persistence_failures_total`. Provider, service,
model, and usage kind are permitted metric labels; call IDs, tenant IDs,
request IDs, transcripts, and phone numbers are not. Grafana's Voice Agent
dashboard shows these aggregates and existing call counts. A metrics export
loss can make Prometheus totals incomplete; reconcile against PostgreSQL.

For a day's per-call comparison, query `call_sessions` joined to
`call_ai_usage`, grouping by `call_id`, tenant, provider, service, and model;
use `counters` for raw usage and keep the two monetary columns separate.
For example, with UTC window parameters:

```sql
SELECT c.id AS call_id, c.tenant_id, c.started_at, u.provider, u.service,
       u.model, u.source, u.counters, u.estimated_cost_usd,
       u.estimated_cost_source, u.provider_cost_usd, u.reconciled_at
FROM call_sessions AS c
LEFT JOIN call_ai_usage AS u ON u.call_id = c.id
WHERE c.started_at >= :from_utc AND c.started_at < :to_utc
ORDER BY c.started_at, c.id, u.service, u.provider, u.model;
```

Count distinct `call_id` values, including rows with no usage. Sum monetary
columns only after checking how many rows are NULL; a partial sum is not a
complete cost total.
Provider reconciliation can later update `provider_cost_usd` and
`reconciled_at` without modifying raw counters or estimates. Soniox's
`client_reference_id` supports direct matching. OpenAI/Azure and ElevenLabs
provider-side request IDs or billing entries are not captured by the pinned
streaming integrations; matching those bills remains follow-up work. The
LiveKit counters are SDK-reported usage, not provider-invoice evidence.

## Local Compose

Backend and Voice Agent use the Docker service URL:

```text
LIVEKIT_URL=ws://livekit:7880
```

The browser uses the host-reachable URL:

```text
LIVEKIT_PUBLIC_URL=ws://localhost:7880
LIVEKIT_NODE_IP=127.0.0.1
LIVEKIT_UDP_PORT=7882
```

The dev LiveKit node binds signaling to `0.0.0.0`, advertises
`LIVEKIT_NODE_IP`, and uses UDP mux on `LIVEKIT_UDP_PORT`. Compose publishes
7880/tcp, 7881/tcp, and 7882/udp. For a LAN browser, replace both public URL
and node IP with the host LAN address. Remote microphone access requires HTTPS
(and `wss://` for LiveKit).

Staging and production use an externally deployed self-hosted LiveKit node.
`LIVEKIT_NODE_IP` must be the address that browser ICE candidates can reach;
TURN, TLS, NAT, and firewall topology remain deployment requirements.

## Voice turn detection

ElevenLabs Scribe v2 realtime owns end-of-speech commits. LiveKit uses
`turn_detection="stt"` with fixed endpointing (`min_delay=0.1`,
`max_delay=0.7`). Server VAD is currently configured with 0.5 seconds of silence,
0.35 activity threshold, 100 ms minimum speech, and 500 ms minimum silence.
Local Silero VAD is also enabled for speech onset and interruption (barge-in);
it does not replace ElevenLabs end-of-speech ownership. These values, provider
models, logical Azure model, and TTS voice come from the call-pinned
`VoiceRuntimeRevision`.

`Policies.cascade.stt_commit.strategy` selects one authority: `local_vad`,
`provider_vad`, or `stt`. For Soniox RT v5, `stt` uses the installed LiveKit
plugin's `FINAL_TRANSCRIPT` followed by `END_OF_SPEECH` events directly;
`LocalVadCommitSTT` is not installed and local VAD does not flush the stream.
Silero VAD remains configured for speech activity and interruption detection.
The Control Plane validates `stt` against the selected deployment's
`supports_native_endpointing` capability. Existing `local_vad` configurations
continue to use the wrapper and its manual finalization behavior.

Soniox emits `PREFLIGHT_TRANSCRIPT` when a response contains finalized text
tokens and no non-final text tokens; this can happen before the speaker stops.
The final-token accumulator persists across messages, while provisional tokens
are accumulated only within each message. An interim-only update does not
restart a preemptive attempt. A later preflight replaces it; final-turn reuse
additionally requires equivalent final transcript, chat context, tools, and
tool choice. Soniox treats both `<end>` and `<fin>` as endpoint markers, emits
`FINAL_TRANSCRIPT` then `END_OF_SPEECH`, and resets accumulated final-token
buffers after endpoint emission. New provisional tokens may follow a preflight
before endpoint detection. A changed final transcript starts a newer attempt
when LiveKit reports it before EOU; otherwise transcript mismatch invalidates
the earlier attempt at turn completion.

LiveKit 1.8.2 handles preflight in `audio_recognition.py`, calls
`AgentActivity.on_preemptive_generation`, and logs `using preemptive generation`
with `preemptive_lead_time` only when it reuses the attempt. With
`preemptive_tts`, synthesis starts before the speech is scheduled, while output
still waits for scheduling and authorization; invalidated speech is canceled.
For development evidence, set `LIVEKIT_LOG_LEVEL=DEBUG` to include the LiveKit
agent and Soniox plugin debug messages; keep that temporary in development.

The current runtime locale mapper intentionally supports Slovak only:
`sk-SK` maps to Soniox `sk`; `cs-CZ` is rejected by the voice deployment's
existing locale validation.

The pinned logical Azure model comes from the effective VoiceRuntime: the
published platform runtime is the default and a published tenant runtime may
override its logical model. Azure endpoint, API version, deployment, provider
credentials, provider timeout/retry, participant wait timeout, and capability
polling remain deployment settings. The deployment is not selected by the
browser or tenant runtime. ElevenLabs STT/TTS language codes are mapped at the
adapter boundary from the pinned Slovak locale (`sk-SK` to `slk`/`sk`); other
locales fail explicitly. Historical calls whose nullable migration-era runtime
revision is absent are not resumable through the new runtime-context endpoint.

The Voice Agent emits `Voice EOU metrics` with transcription and endpointing
delays. Compare a real smoke test before tuning the values. Candidate variants:

| Variant | ElevenLabs silence | LiveKit min delay |
| --- | ---: | ---: |
| A | 1.0 s | 0.2 s |
| B | 0.7 s | 0.0 s |
| C | 0.5 s | 0.1 s |

For barge-in, test a long agent utterance and interrupt it after the second
word. TTS should stop and the new user turn should be transcribed.

## Failure consistency

If dispatch persistence or participant token issuance fails, Backend Core
best-effort deletes the dispatch and then the automatically created room.
Cleanup errors are suppressed so they cannot hide the original setup error.

There is a known distributed crash window: dispatch creation can succeed before
`provider_dispatch_id` is persisted. The current bounded slice accepts this
gap. A future reconciliation/outbox/saga should close it; SQL transactions must
not be extended across the LiveKit API call.
