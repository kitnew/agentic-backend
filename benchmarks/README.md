# Standalone voice latency benchmarks

Set the provider variables in `benchmarks/.env.benchmark.local` as shown by
`benchmarks/.env.example`. Use the included fixed WAV:

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
runners start direct ElevenLabs TTS when the first token from LiveKit's
sentence tokenizer is emitted, while model output continues. They approximate
production chunk timing but omit LiveKit playout, SIP, provider connection
pooling, runtime prompts, and real turn detection. The Realtime synthetic runner
uses a manually committed provider turn; it does not replicate server VAD.
The STT runner's connection time is separate from `audio_end_to_final_ms`.
The network runner's DNS/TCP/TLS timings are separate from HEAD response and
WebSocket handshake timings; HEAD responses can be 401/404 and still measure
setup. Cold/reused HEAD requests use one client; WebSocket reuse is not
approximated by a new connection.
