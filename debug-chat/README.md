# LiveKit Voice Debug Console

Browser-only debug UI for the production voice path. It requests a session from Backend Core,
joins LiveKit, publishes microphone audio, and shows connection, transcript, tool, and latency
events.

## Run

```bash
python3 debug-chat/server.py
```

Open <http://127.0.0.1:8080>. Set `BACKEND_URL` only when Backend Core is not available at
`http://127.0.0.1:8000`; `DEBUG_CHAT_HOST` and `DEBUG_CHAT_PORT` control the local debug server.

Microphone access requires localhost or HTTPS.
