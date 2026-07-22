# Agentic Backend

Voice-only hospitality agent built on LiveKit Agents.

## Runtime topology

```text
browser or SIP participant
  -> LiveKit
  -> app.voice_agent
  -> Backend Core LiveKit contracts
  -> capability worker
  -> tenant providers such as Google Sheets
```

The conversational runtime lives only in `app/voice_agent`. The FastAPI backend does not
run an agent; it issues LiveKit sessions, persists final conversation messages, and executes
capabilities through authenticated LiveKit-specific endpoints.

## Services

- `api`: backend core on port 8000
- `voice-agent`: LiveKit Agents worker and health server on port 8081
- `capability-worker`: Redis-backed capability execution
- `postgres`: conversation and tool-call persistence
- `redis`: capability command transport

LiveKit itself is provided externally. Set both `LIVEKIT_INTERNAL_URL` and
`LIVEKIT_PUBLIC_URL` to the configured LiveKit deployment.

## Setup

```bash
cp .env.example app/.env
docker compose --env-file app/.env up --build --wait
```

Required credentials are documented in `.env.example`. Google Sheets credentials belong
in `app/secrets/google-service-account.json`.

## Backend contracts

The supported voice boundary is under `/api/v1/voice/livekit`:

- `POST /sessions`: create a room-scoped participant token and agent dispatch
- `POST /messages`: persist a final LiveKit user or assistant message
- `POST /tools`: execute an enabled tenant capability for a persisted user turn

The worker-side client is `app/voice_agent/backend_client.py`; shared request, response,
and authentication DTOs are in `app/contracts/livekit.py`.

## Debug client

```bash
python debug-chat/server.py
```

Open <http://localhost:3000>. The client creates a LiveKit session through the backend and
then sends microphone audio directly through LiveKit.

## Verification

```bash
uv run pytest -q
node --test debug-chat/livekit-controller.test.js
docker compose --env-file app/.env config --quiet
```
