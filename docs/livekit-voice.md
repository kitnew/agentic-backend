# LiveKit voice deployment notes

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

Cascade Soniox STT uses the installed LiveKit Soniox plugin's
`PREFLIGHT_TRANSCRIPT` events for stable tokens. `LocalVadCommitSTT` forwards
these events immediately, so LiveKit's existing preemptive generation can run
before the turn endpoint. The wrapper still gates provider
`END_OF_SPEECH` until local VAD requests a flush; with the current local-VAD
commit policy, local VAD remains the turn-completion authority. `RuntimeResolver`
rejects the ElevenLabs-specific `provider_vad` commit policy for Soniox.

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
