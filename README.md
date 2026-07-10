# agentic-backend

## Voice Message Mode

Voice mode is a universal, channel-independent request path for:

audio input -> STT -> existing text agent pipeline -> TTS -> audio output

It is not realtime voice. There is no WebRTC, streaming, interruption/barge-in, phone, SIP, or speech-to-speech support in this mode.

### Flow

`POST /api/v1/voice/messages` accepts multipart form data with `tenant_id`, `channel`, optional `conversation_id`, optional `external_user_id`, optional JSON `metadata`, and `audio_file`.

The backend:

1. Loads the tenant config and rejects the request unless `voice.enabled: true`.
2. Validates the audio file content type and max size.
3. Transcribes audio with the configured STT provider.
4. Sends the transcript into the existing `ProcessIncomingMessage` text pipeline as `channel: voice` with `input_mode: voice` metadata.
5. Synthesizes the agent text response with the configured TTS provider.
6. Stores generated audio locally under `VOICE_AUDIO_STORAGE_DIR` and returns an `audio_url`.

There is still one canonical agent/message path; voice does not duplicate LangGraph or capability execution logic.

### ElevenLabs Configuration

Set the API key in the environment:

```bash
export ELEVENLABS_API_KEY="..."
```

Configure a tenant explicitly:

```yaml
voice:
  enabled: true
  max_file_size_bytes: 26214400

  stt:
    provider: elevenlabs
    model: scribe_v2
    language: sk
    keyterms:
      - rezervacia
      - parkovanie
      - terasa
      - alergeny

  tts:
    provider: elevenlabs
    model: eleven_flash_v2_5
    voice_id: "YOUR_ELEVENLABS_VOICE_ID"
    output_format: mp3_44100_128
    language: sk

  fallback:
    send_text_if_tts_fails: true
    continue_if_stt_metadata_missing: true
```

`voice.enabled` defaults to `false`, so existing tenant configs are not enabled for voice unless they opt in. If `voice.tts.voice_id` is empty, `ELEVENLABS_VOICE_ID` can be used as a runtime fallback.

Generated files are served from `/api/v1/voice/audio/...` by default. Override storage with:

```bash
export VOICE_AUDIO_STORAGE_DIR="var/voice-audio"
export VOICE_AUDIO_PUBLIC_BASE_URL="/api/v1/voice/audio"
```

FastAPI multipart parsing requires `python-multipart` in the runtime environment.

## Minimal Voice WebSocket Stream

`/api/v1/voice/stream` is a first-step realtime voice entrypoint. It accepts one
WebSocket connection per voice call and creates an isolated in-process
`VoiceSession` for that connection. It buffers audio chunks and processes one
complete voice turn through the existing synchronous voice pipeline when the
client commits the input audio. True streaming STT/TTS is intentionally not
wired here yet.

Connect with a tenant query parameter:

```text
ws://localhost:8000/api/v1/voice/stream?tenant_id=demo_restaurant
```

On connect, the server sends a `session_started` event containing a unique
`call_session_id`. Clients can send JSON events, binary audio chunks, or JSON
base64 audio chunks, then commit the buffered audio:

```json
{"type":"ping"}
{"type":"audio_chunk","audio_base64":"ZmFrZS1hdWRpbw=="}
{"type":"input_audio_commit","content_type":"audio/webm","filename":"turn.webm"}
{"type":"session_end"}
```

On commit, the server sends `processing_started`, transcript/assistant/audio
events when available, and finally `turn_completed`. The existing REST voice
pipeline remains unchanged.

Manual smoke test:

```bash
uvicorn app.main:app --reload
.venv/bin/python scripts/voice_ws_smoke.py
```

### Curl Example

```bash
curl -X POST "http://localhost:8000/api/v1/voice/messages" \
  -F tenant_id="demo_restaurant" \
  -F channel="browser" \
  -F external_user_id="customer-123" \
  -F metadata='{"source":"debug"}' \
  -F audio_file=@"app/sample.webm;type=audio/webm"
```

Example response fields:

```json
{
  "conversation_id": "...",
  "transcript": "Chcem rezervaciu dnes vecer",
  "response_text": "...",
  "audio_url": "/api/v1/voice/audio/....mp3",
  "metadata": {
    "stt_provider": "elevenlabs",
    "tts_provider": "elevenlabs",
    "language": "sk",
    "audio_duration_ms": 1200,
    "content_type": "audio/webm",
    "warnings": []
  }
}
```

### Current Limitations

- Not realtime.
- No streaming STT or TTS.
- No interruption or barge-in.
- No phone, SIP, WhatsApp, Telegram, or browser-specific logic.
- Local audio storage is intentionally minimal; replace `LocalVoiceAudioStorage` with durable object storage before production use across multiple app instances.
