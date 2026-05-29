# agentic-backend

Minimal FastAPI backend for testing AI-agent workflows for hotel and restaurant businesses. It is designed to be called from n8n HTTP Request nodes and can optionally call an n8n webhook when a reservation request is created.

## Install

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs are available at:

```text
http://localhost:8000/docs
```

## Seed Demo Data

```bash
curl -X POST http://localhost:8000/api/v1/demo/seed
```

This creates or returns the `Demo Restaurant` tenant and demo knowledge documents for opening hours, address, parking, and menu summary.

## Chat Example

Replace `PUT_TENANT_ID_HERE` with the tenant ID returned by the seed endpoint.

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "PUT_TENANT_ID_HERE",
    "channel": "n8n",
    "external_user_id": "demo-user-1",
    "conversation_id": null,
    "message": "Dobrý deň, chcem rezervovať stôl zajtra o 19:00 pre 4 osoby."
  }'
```

The backend stores the conversation, messages, creates a pending reservation request, logs tool calls, and returns a deterministic assistant reply.

## n8n HTTP Request Node

Use an HTTP Request node with:

- Method: `POST`
- URL: `http://YOUR_BACKEND_HOST:8000/api/v1/chat`
- Body Content Type: JSON
- Body:

```json
{
  "tenant_id": "PUT_TENANT_ID_HERE",
  "channel": "n8n",
  "external_user_id": "{{$json.user_id}}",
  "conversation_id": null,
  "message": "{{$json.message}}"
}
```

## n8n Webhook Callback

To let n8n receive reservation-created events, set `N8N_WEBHOOK_URL` in `backend/.env` to your n8n webhook URL and restart Uvicorn.

To send confirmation events back from n8n to this backend:

```bash
curl -X POST http://localhost:8000/api/v1/n8n/events \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "PUT_TENANT_ID_HERE",
    "event_type": "staff_confirmed_reservation",
    "payload": {
      "reservation_request_id": "PUT_RESERVATION_ID_HERE",
      "status": "confirmed",
      "note": "Confirmed manually by staff"
    }
  }'
```

Supported callback event types:

- `staff_confirmed_reservation`
- `staff_rejected_reservation`

## Tests

```bash
cd backend
source .venv/bin/activate
pytest
```
