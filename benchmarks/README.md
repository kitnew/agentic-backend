# Standalone voice latency benchmarks

Set the provider variables in `benchmarks/.env.benchmark.local` as shown by
`benchmarks/.env.example`. Use the included fixed WAV:

```bash
uv run --no-sync python benchmarks/stt/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/stt/run.py --provider soniox --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/stt/diagnose_soniox.py
uv run --no-sync python benchmarks/pipeline/cascade/soniox.py --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/pipeline/cascade/soniox.py --stable-final-prefix-preflight --soniox-region global --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python -m benchmarks.results.compare_stable_prefix --cascade benchmarks/pipeline/cascade/artifacts/TIMESTAMP
uv run --no-sync python -m benchmarks.results.compare_soniox --soniox-stt benchmarks/stt/artifacts/TIMESTAMP --soniox-cascade benchmarks/pipeline/cascade/artifacts/TIMESTAMP --soniox-diagnostic benchmarks/stt/artifacts/TIMESTAMP
uv run --no-sync python benchmarks/tts/run.py
uv run --no-sync python benchmarks/network/run.py
uv run --no-sync python benchmarks/pipeline/cascade/run.py --audio benchmarks/fixtures/audio/sk_basic.wav --min-sentence-chars 20
uv run --no-sync python benchmarks/pipeline/cascade/run.py --audio benchmarks/fixtures/audio/sk_basic.wav --min-sentence-chars 20 --llm-provider openai --service-tier fast
uv run --no-sync python benchmarks/pipeline/realtime/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
uv run --no-sync python benchmarks/pipeline/half_cascade/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
```

For cascade, replace `20` with the published runtime's
`tts.tokenizer.min_sentence_chars`; when that value is unavailable, the manifest
records the exact value used. Cascade uses LiveKit's sentence tokenizer. For
Eleven v3, production half-cascade uses LiveKit's default word tokenizer because
`auto_mode=False`; its synthetic runner uses the same first-token boundary.
Both start direct ElevenLabs TTS while model output continues. These are
synthetic provider pipelines; they omit LiveKit playout, SIP, provider connection
pooling, realistic conversation history, and real turn detection. STT and
cascade pace 50 ms PCM16 chunks in real time. Realtime and half-cascade
burst-upload the fixture, then manually commit the provider turn. Their
input-end boundary is not production end-of-utterance latency. The STT runner's
connection time is separate from `audio_end_to_final_ms`.
Soniox uses the installed LiveKit 1.8.2 plugin and its `PREFLIGHT_TRANSCRIPT`,
`FINAL_TRANSCRIPT`, and `END_OF_SPEECH` events. `SONIOX_REGION=EU` selects the
EU endpoint; `GLOBAL` selects the global endpoint. `BENCH_SONIOX_API_KEY` can
override the local file without entering the key in any artifact. The 50 ms
input timestamps mark `push_frame` into the plugin's queue; provider transport
send occurs asynchronously. Signed preflight lead uses this logical input-end
boundary. First-token prefix accuracy divides the longest matching normalized
leading-token sequence by the first preflight's normalized token count.

The Soniox cascade is labeled `synthetic_preemptive`. It models LiveKit 1.8.2's
three-attempt limit, replacement on each preflight, and transcript equivalence
at commit; fixed context/tools are assumed. It commits at Soniox
`END_OF_SPEECH`, whereas the production path uses local VAD. It does not run an
AgentSession or measure caller playout. `first_audio_eligible_lower_bound_ms`
is `max(turn commit, first synthesized byte)`, a lower bound only. Compare
preemptive TTS synthesis timing separately from this boundary. The fixed
`sk_basic.wav` is the only human-speech fixture; results are fixture-specific.
The optional diagnostic stores per-message token counts and final/provisional
states without raw WebSocket payloads or credentials. It explains whether the
plugin's preflight condition was ever met for a fixture.
`--stable-final-prefix-preflight` is a benchmark-only experiment. It injects
LiveKit `PREFLIGHT_TRANSCRIPT` events containing accumulated provider-final
tokens even when a provisional tail is present. The stock Soniox plugin still
owns `FINAL_TRANSCRIPT` and `END_OF_SPEECH`; provisional tokens never enter the
experimental preflight. The three variants are a stock preemptive control,
stable-prefix preemptive LLM, and stable-prefix preemptive LLM + TTS. An EU
region key is required when using `--soniox-region eu`; a GLOBAL/US key can
receive HTTP 401 from that endpoint. Word thresholds count complete leading
words matching the final transcript; Soniox may finalize a midword fragment
that appears in the raw preflight but gives no complete-word lead.
The network runner's DNS/TCP/TLS timings are separate from HEAD response and
WebSocket handshake timings; HEAD responses can be 401/404 and still measure
setup. Cold/reused HEAD requests use one client; WebSocket reuse is not
approximated by a new connection.
