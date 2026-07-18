# Debug Chat

Minimal browser UI for sending messages to the agentic backend and inspecting the full API response.

It also includes a browser microphone debug control for the non-realtime voice message mode:

record microphone audio -> upload to `/api/v1/voice/messages` -> show transcript/response -> play returned assistant audio.

## Run

From the repository root:

```bash
python3 debug-chat/server.py
```

Open http://127.0.0.1:8080.

Optional environment variables:

```bash
BACKEND_URL=http://127.0.0.1:8000 API_PATH=/api/v1/messages DEBUG_CHAT_PORT=8080 python3 debug-chat/server.py
```

## Manual Voice Check

Microphone access requires localhost or HTTPS.

1. Enable voice for the tenant, for example `voice.enabled: true` in `app/tenants/configs/demo_restaurant.yaml`.
2. Start the backend:

```bash
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

3. Start the debug UI:

```bash
python3 debug-chat/server.py
```

4. Open http://127.0.0.1:8080, keep `Tenant ID` as `demo_restaurant`, and switch input mode from `Text` to `Voice`.
5. Click `Start recording`, say `Ahoj`, then click `Stop recording`.
6. Verify that transcript and assistant response appear, returned audio plays or can be played manually, and the `Conversation ID` field is reused for the next recording.
