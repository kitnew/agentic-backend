# Voice turn latency baseline

The real-call collector is opt-in. Set `VOICE_TURN_BENCHMARK_DIR` to a writable,
persistent directory in the **Voice Agent process**, then start the Voice Agent
normally. Optionally set `VOICE_TURN_TEST_LABEL` to a short non-sensitive label.
Place a normal test call and speak several phrases, including:

> Dobrý deň, chcel by som si rezervovať dvojlôžkovú izbu od dvadsiateho piateho do dvadsiateho šiesteho septembra.

Each call creates `<UTC timestamp>-<call ID>/manifest.json` and `turns.jsonl`.
After the call, copy that directory to `benchmarks/e2e/artifacts/` and run:

```bash
uv run --no-sync python benchmarks/e2e/analyze.py benchmarks/e2e/artifacts/<call-directory>
```

For the deployment Compose stack, put `VOICE_TURN_BENCHMARK_DIR=/tmp/voice-turn-benchmarks`
and optionally `VOICE_TURN_TEST_LABEL=latency-baseline` in the deployment env file,
then start the normal `voice-agent` service. The deployment container has a
read-only filesystem with a writable `/tmp` tmpfs. Copy artifacts **before**
restarting the container:

```bash
docker compose -f infrastructure/compose/docker-compose.yml -f infrastructure/compose/docker-compose.deploy.yml --env-file infrastructure/compose/.env.production up -d voice-agent
container=$(docker compose -f infrastructure/compose/docker-compose.yml -f infrastructure/compose/docker-compose.deploy.yml --env-file infrastructure/compose/.env.production ps -q voice-agent)
docker cp "$container:/tmp/voice-turn-benchmarks/." benchmarks/e2e/artifacts/
```

The analyzer writes `summary.json` and `summary.csv` beside the raw records.
Raw `turns.jsonl` remains authoritative. No transcript, prompt, audio, phone
number, provider key, or endpoint URL is written. Records contain opaque call,
turn, and tenant IDs. A trace ID is null when OpenTelemetry is disabled.

All `timestamps_ns` values use `time.perf_counter_ns()` in one Voice Agent
process; the SDK's `perf_counter()` TTS start is converted to nanoseconds in
that same process. UTC is for correlation only. Negative-order or unavailable
intervals are null. Do not sum independent medians or observer STT into a
critical-path total. `causal_stage_sum_ms` is present only when every
nonoverlapping stage is observed and its sum agrees with the directly measured
total; otherwise it is null. The exact server-side E2E value is
`output_boundary_proxy - speech_end_proxy`: estimated VAD speech end for
cascade, or receipt of Realtime server speech-stop for Realtime paths, through
LiveKit RoomIO's `playback_started` event. In LiveKit Agents 1.8.2 this event
fires immediately before `_audio_source.capture_frame` in `_forward_audio`.
It is **not** the first RTP packet, SIP delivery, or the instant a caller hears
sound. Those boundaries are unavailable from the application.

For cascade, the configured `turn_detection="stt"` means STT final can precede
LiveKit's accepted end-of-turn callback. Preemptive generation can also start
the LLM before that callback. The analyzer leaves reversed intervals null.
For Realtime and half-cascade, `input_speech_stopped` and
`generation_created` are directly observed on the SDK Realtime session;
provider commit acknowledgment is unavailable. Standalone ElevenLabs STT is
an observer in these two architectures. Half-cascade causally streams Realtime
text through the LiveKit/ElevenLabs tokenizer and ElevenLabs TTS.

`first_speakable` is the SDK's `USERDATA_TTS_STARTED_TIME`, sampled at the
first chunk sent to ElevenLabs after the real production tokenizer. It is
reconstructed from the first decoded TTS frame, so missing output makes it
unavailable. `tts_first_audio` is that first decoded frame, not the provider's
first network byte. `playout_enqueue` and caller audibility remain null.
The artifact manifest repeats these semantics for each call.

## Existing direct and synthetic runners

Set the required provider variables in `benchmarks/.env.benchmark.local` as
shown by `benchmarks/.env.example`. Use the included fixed WAV:

```bash
uv run --no-sync python benchmarks/stt/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/tts/run.py
uv run --no-sync python benchmarks/network/run.py
uv run --no-sync python benchmarks/pipeline/cascade/run.py --audio benchmarks/fixtures/audio/sk_basic.wav --min-sentence-chars 20
uv run --no-sync python benchmarks/pipeline/realtime/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/pipeline/half_cascade/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
```

For cascade, replace `20` with the published runtime's
`tts.tokenizer.min_sentence_chars`. The synthetic cascade and half-cascade
runners now start direct ElevenLabs TTS when the first token from LiveKit's
sentence tokenizer is emitted, while model output continues. They approximate
production chunk timing but omit LiveKit playout, SIP, provider connection
pooling, runtime prompts, and real turn detection. The Realtime synthetic runner
uses a manually committed provider turn; it does not replicate server VAD.
The STT runner's connection time is separate from `audio_end_to_final_ms`.
The network runner's DNS/TCP/TLS timings are separate from HEAD response and
WebSocket handshake timings; HEAD responses can be 401/404 and still measure
setup. Cold/reused HEAD requests use one client; WebSocket reuse is not
approximated by a new connection.
