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
run an agent; it owns durable call sessions, messages, terminal state, finalization, and
capability routing through authenticated LiveKit-specific endpoints. `app/agent` contains
transport-independent prompts and schemas. There is no separate `app/voice` runtime package.

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
# Fill the blank provider/LiveKit values and generate each local secret independently:
# openssl rand -hex 32
docker compose --env-file app/.env up --build --wait
```

Only blank values in `.env.example` need attention; Compose owns the remaining local
defaults. Google Sheets credentials belong in `app/secrets/google-service-account.json`.

## Backend contracts

The supported voice boundary is under `/api/v1/voice/livekit`:

- `POST /sessions`: create an authorized room-scoped participant token and agent dispatch
- `POST /messages`: persist a final LiveKit user or assistant message
- `POST /tools`: execute an enabled tenant capability for a persisted user turn
- `POST /finalize`: make a call terminal and enqueue idempotent post-call processing

`call_sessions` uses `active -> completed|failed` for the call and
`pending -> processing -> completed|failed` for finalization. The existing capability worker
builds the transcript from PostgreSQL messages, generates the Slovak summary, and writes
Google Sheets with `call_session_id` developer metadata as the external idempotency key.

`POST /sessions` accepts a short-lived HMAC Bearer token whose signed claims contain the
caller identity and allowed tenant IDs. Its `LIVEKIT_SESSION_AUTH_SECRET` is separate from
the worker-only `VOICE_SESSION_TOKEN_SECRET`. Tool retries are keyed durably by
`tenant_id + call_session_id + tool_call_id`; PostgreSQL stores the request fingerprint and
terminal response while Redis reuses the durable tool-call ID as its command ID.

The worker-side client is `app/voice_agent/backend_client.py`; shared HTTP, dispatch,
authentication, and voice-turn DTOs are in `app/contracts`.

## Debug client

```bash
python debug-chat/server.py
```

Open <http://localhost:8080>. The client creates a LiveKit session through the backend and
then sends microphone audio directly through LiveKit. The API must explicitly enable the
development-only path with `APP_ENV=development`, `LIVEKIT_DEBUG_AUTH_ENABLED=true`, and
`LIVEKIT_DEBUG_ALLOWED_TENANTS=demo_restaurant,penzion_grand`. No debug token is required;
the proxy marks its Backend request automatically.

## Database migration

The API applies `app/infrastructure/migrations/*.sql` under the existing PostgreSQL startup
advisory lock. To verify the lifecycle table manually:

```bash
docker compose --env-file app/.env exec -T postgres \
  psql -U agentic -d agentic -c '\d tool_calls'
```

## Verification

```bash
uv run pytest -q
node --test debug-chat/livekit-controller.test.js
docker compose --env-file app/.env config --quiet
```

## Production

The bounded single-VM Docker Compose deployment is documented in
[`docs/production-deployment.md`](docs/production-deployment.md). It uses
`docker-compose.prod.yml` as an override and does not change the development command above.
