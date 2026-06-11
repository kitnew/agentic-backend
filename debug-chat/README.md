# Debug Chat

Minimal browser UI for sending messages to the agentic backend and inspecting the full API response.

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
