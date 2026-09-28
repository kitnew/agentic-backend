# Standalone voice latency benchmarks

Set the provider variables in `benchmarks/.env.benchmark.local` as shown by
`benchmarks/.env.example`. Use the included fixed WAV:

```bash
uv run --no-sync python benchmarks/stt/run.py --audio benchmarks/fixtures/audio/sk_basic.wav
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
The network runner's DNS/TCP/TLS timings are separate from HEAD response and
WebSocket handshake timings; HEAD responses can be 401/404 and still measure
setup. Cold/reused HEAD requests use one client; WebSocket reuse is not
approximated by a new connection.
