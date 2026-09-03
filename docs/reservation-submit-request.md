# `reservation.submit_request@1`

This capability records a reservation request for later confirmation. It never means that a reservation is confirmed.

Backend Core owns the semantic definition, validation, canonical input, immutable plan compilation, invocation state, encrypted integration credentials, and outbox. Job Worker owns external execution, lookup-before-append, provider retries, and typed technical results. Voice Agent receives only the tool name, description, announcement, input schema, and semantic result.

Tenants that set `business_policy.requires_final_confirmation` use the Backend-owned confirmation lifecycle: `POST /internal/v1/calls/{call_id}/capability-confirmations` creates an opaque snapshot, and `POST /internal/v1/calls/{call_id}/capability-confirmations/{confirmation_id}/confirm` atomically consumes it with the invocation and outbox transaction. `check_availability` remains deferred.

`jsonschema` provides Draft 2020-12 validation. `jsonata-python` is the maintained pure-Python JSONata evaluator; it receives and returns JSON-compatible values only and has no registered host functions. `google-auth` resolves service-account credentials in Job Worker.

## Credential setup

Create, configure, set a credential from stdin, and enable the Backend-owned integration. The Worker retrieves the decrypted material only for the invocation pinned to that integration; it never receives credentials in Redis or configuration.

```bash
agentctl integration create tenant-a reservations \
  --provider google_sheets
printf '%s' '{"service_account":{"client_email":"...","private_key":"...","token_uri":"https://oauth2.googleapis.com/token"}}' \
  | agentctl integration set-secret tenant-a reservations
agentctl integration enable tenant-a reservations
```

The root `INTEGRATION_ENCRYPTION_KEY` is the only deployment secret for integration storage. Credentials are AES-GCM encrypted and versioned in PostgreSQL; changing, rotating, revoking, or enabling an integration needs no container restart. `agentctl integration test` performs non-destructive readiness validation (config, active credential, and decryption); real provider requests remain capability-driven.

Share the target test spreadsheet with the service-account `client_email`.

## Penzión Grand managed webhook configuration

Create a Backend integration connection with provider-specific public configuration and set the URL/API key through stdin:

```bash
agentctl integration create penzion-grand penzion-grand-reservation-submit \
  --provider managed_webhook \
  --config-json '{"allowed_hosts":["hook.eu1.make.com"]}'
printf '%s' '{"url":"https://hook.eu1.make.com/...","api_key":"..."}' \
  | agentctl integration set-secret penzion-grand penzion-grand-reservation-submit
agentctl integration enable penzion-grand penzion-grand-reservation-submit
```

The published capability execution uses the generic managed webhook plan:

```json
{
  "plan_type": "managed_webhook.post_json.v1",
  "connection_id": "<managed-webhook-connection-uuid>",
  "mapping_language": "jsonata",
  "mapping_contract_version": 1,
  "mapping_engine": "jsonata-python",
  "mapping_engine_version": "0.7.0",
  "timeout_seconds": 10,
  "request_mapping": "{\"check_in\": business.stay.check_in, \"check_out\": business.stay.check_out, \"guest_name\": business.guest.name, \"caller_phone\": metadata.caller_phone, \"reservation_phone\": business.guest.phone, \"email\": business.guest.email ? business.guest.email : \"\", \"room_type\": business.allocation.room_type, \"room_count\": business.allocation.room_count}"
}
```

The Make scenario receives the generic envelope, uses `operation_id` for its hidden `reservations_new` column K, and returns the standard success/failure response envelope. Backend and Worker do not know the Sheet layout.

## Tenant A configuration

Use the published Control Plane component revisions and connection ID returned by the APIs:

```json
{
  "schema_version": 2,
  "localization": {"default_locale": "en", "timezone": "Europe/Bratislava"},
  "agent": {"display_name": "Reservations", "greeting": "How may I help?"},
  "conversation": {"scope": "property_only"},
  "capabilities": {
    "reservation.submit_request": {
      "enabled": true,
      "semantic_version": 1,
      "description": "Submit a reservation request.",
      "announcement": "I will submit your reservation request now.",
      "agent_input_schema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
          "guest_name": {"type": "string", "minLength": 1, "description": "Name of the guest", "x-canonical-field": "guest.name"},
          "check_in": {"type": "string", "format": "date", "description": "Arrival date", "x-canonical-field": "stay.check_in"},
          "check_out": {"type": "string", "format": "date", "description": "Departure date", "x-canonical-field": "stay.check_out"}
        },
        "required": ["guest_name", "check_in", "check_out"],
        "additionalProperties": false
      },
      "business_policy": {},
      "execution": {
        "plan_type": "google_sheets.append_values.v1",
        "mapping_language": "jsonata",
        "mapping_contract_version": 1,
        "mapping_engine": "jsonata-python",
        "mapping_engine_version": "0.7.0",
        "connection_id": "00000000-0000-0000-0000-000000000020",
        "spreadsheet_id": "tenant-a-spreadsheet-id",
        "sheet_name": "Reservations",
        "append_range": "A:D",
        "value_input_option": "RAW",
        "idempotency": {"lookup_range": "A:A", "operation_id_column_index": 0},
        "request_mapping": "{\"rows\": [[metadata.operation_id, business.guest.name, business.stay.check_in, business.stay.check_out]]}"
      },
      "validation_fixtures": [
        {"guest_name": "Fixture Guest", "check_in": "2030-01-01", "check_out": "2030-01-02"},
        {"guest_name": "Fixture Guest", "check_in": "2031-01-01", "check_out": "2031-01-02"}
      ]
    }
  }
}
```

## Tenant B configuration

Tenant B uses the same semantic capability and handler. Only its profile differs:

```json
{
  "schema_version": 2,
  "localization": {"default_locale": "en", "timezone": "Europe/Bratislava"},
  "agent": {"display_name": "Booking Requests", "greeting": "How may I help?"},
  "conversation": {"scope": "property_only"},
  "capabilities": {
    "reservation.submit_request": {
      "enabled": true,
      "semantic_version": 1,
      "description": "Submit a reservation request.",
      "announcement": "I will submit your reservation request now.",
      "agent_input_schema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
          "guest_name": {"type": "string", "minLength": 1, "description": "Full name of the guest", "x-canonical-field": "guest.name"},
          "reservation_phone": {"type": "string", "minLength": 1, "description": "Confirmed reservation contact phone", "x-canonical-field": "guest.phone"},
          "email": {"type": "string", "format": "email", "description": "Guest email", "x-canonical-field": "guest.email"},
          "check_in": {"type": "string", "format": "date", "description": "Arrival date", "x-canonical-field": "stay.check_in"},
          "check_out": {"type": "string", "format": "date", "description": "Departure date", "x-canonical-field": "stay.check_out"},
          "room_type": {"type": "integer", "enum": [2, 3, 4], "x-canonical-field": "allocation.room_type"},
          "room_count": {"type": "integer", "minimum": 1, "x-canonical-field": "allocation.room_count"}
        },
        "required": ["guest_name", "reservation_phone", "check_in", "check_out", "room_type", "room_count"],
        "additionalProperties": false
      },
      "business_policy": {"requires_final_confirmation": true, "requires_availability_proof": false, "requires_caller_phone": true},
      "execution": {
        "plan_type": "google_sheets.append_values.v1",
        "mapping_language": "jsonata",
        "mapping_contract_version": 1,
        "mapping_engine": "jsonata-python",
        "mapping_engine_version": "0.7.0",
        "connection_id": "00000000-0000-0000-0000-000000000021",
        "spreadsheet_id": "tenant-b-spreadsheet-id",
        "sheet_name": "Booking Requests",
        "append_range": "A:K",
        "value_input_option": "RAW",
        "idempotency": {"lookup_range": "K:K", "operation_id_column_index": 10},
        "request_mapping": "{\"rows\": [[business.stay.check_in, business.stay.check_out, business.guest.name, metadata.caller_phone, business.guest.phone, $exists(business.guest.email) ? business.guest.email : \"\", business.allocation.room_type, business.allocation.room_count, \"\", false, metadata.operation_id]]}"
      },
      "validation_fixtures": [
        {"guest_name": "Fixture Guest", "reservation_phone": "+421900000000", "check_in": "2030-01-01", "check_out": "2030-01-02", "room_type": 4, "room_count": 1},
        {"guest_name": "Fixture Guest", "reservation_phone": "+421900000001", "check_in": "2031-01-01", "check_out": "2031-01-02", "room_type": 4, "room_count": 1}
      ]
    }
  }
}
```

Create the draft with `POST /admin/v1/tenants/{tenant_id}/config/drafts`, validate it with `POST .../{revision_id}/validate`, then publish it with `POST .../{revision_id}/publish`. Publication is local and has no Google side effect.

## Manual Google Sheet smoke test

For `reservations_new`, keep columns A:J as business data and add a hidden technical column K named `operation_id`. Configure `append_range` as `A:K`, `lookup_range` as `K:K`, and `operation_id_column_index` as `10`. The Worker never interprets the business columns; it only uses K for provider-side duplicate detection.

1. Put the service-account map in the Job Worker secret environment and start PostgreSQL, Redis, Backend, Job Worker, LiveKit, and Voice Agent.
2. Create an active integration connection, create/validate/publish one of the configurations above, and start a new call so it pins that revision.
3. Invoke `reservation_submit_request` once and poll the returned invocation until terminal. Confirm the Sheet contains the operation ID and configured cells and the semantic result is `request_submitted`.
4. Re-deliver the same Redis job or retry after withholding the first Backend callback. Confirm the driver finds the operation ID and returns `deduplicated: true` without a normal second append.
5. Confirm Backend and Worker logs contain IDs and statuses but no guest fields, rows, credential references, or credentials.

The guarantee is at-least-once delivery plus Backend invocation uniqueness, one logical job ID, and provider lookup-before-append. Google Sheets does not provide an atomic lookup-and-append transaction, so two workers racing before either append can still create duplicate rows. The operation-ID column makes that residual race observable and repairable; this slice does not claim exactly-once delivery.

## PII retention policy

`canonical_input`, compiled Sheet rows, and undispatched Redis/outbox payloads are treated as personal data. Terminal invocation PII is purged after 30 days; the immutable semantic result, operation metadata, safe provider range, and status remain. Dispatched outbox rows are deleted after 7 days. Redis stream trimming is capped at 10,000 entries and runs only when the capability consumer group has no pending entries; the dead-letter stream is capped separately. Pending messages are never trimmed by maintenance. Configure these values with the `CAPABILITY_*_RETENTION_*` environment variables and grant database access only to the Backend service and approved operators.

Google Sheets is an external operational destination, so its row retention/archival policy must be managed by the tenant operator; Backend cleanup deliberately does not delete provider rows.

The Worker/Backend execution plan records the JSONata contract and engine identity (`jsonata-python` `0.7.0`). Mapping fixtures are executed at publication and in conformance tests so an engine upgrade cannot silently reinterpret an immutable revision.

The provider timeout is 10 seconds, Voice Agent polling budget is 15 seconds, and job expiry is 10 minutes. If polling reaches its budget, Voice Agent returns `request_submission_pending` and does not submit again; the existing Backend job may still finish and its idempotent result is retained.
