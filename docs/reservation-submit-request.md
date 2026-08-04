# `reservation.submit_request@1`

This capability records a reservation request for later confirmation. It never means that a reservation is confirmed.

Backend Core owns the semantic definition, validation, canonical input, immutable plan compilation, invocation state, and outbox. Job Worker owns Google credentials, lookup-before-append, provider retries, and typed technical results. Voice Agent receives only the tool name, description, announcement, input schema, and semantic result.

`jsonschema` provides Draft 2020-12 validation. `jsonata-python` is the maintained pure-Python JSONata evaluator; it receives and returns JSON-compatible values only and has no registered host functions. `google-auth` resolves service-account credentials in Job Worker.

## Credential setup

Create the Backend connection through the admin API; the credential value stays only in Job Worker:

```bash
curl -X POST "$BACKEND_URL/admin/v1/tenants/$TENANT_ID/integration-connections" \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key":"reservations","provider":"google_sheets","credential_ref":"tenant-a-sheets"}'
```

Provide an allowlisted reference-to-service-account map to Job Worker. In production, inject this environment value from the deployment secret manager rather than committing it:

```text
GOOGLE_SHEETS_CREDENTIALS_JSON={"tenant-a-sheets":{"type":"service_account","project_id":"...","private_key_id":"...","private_key":"...","client_email":"...","client_id":"...","token_uri":"https://oauth2.googleapis.com/token"}}
```

Share the target test spreadsheet with the service-account `client_email`.

## Tenant A configuration

Use the published prompt-bundle revision and connection ID returned by the APIs:

```json
{
  "schema_version": 2,
  "prompt_bundle_revision_id": "00000000-0000-0000-0000-000000000010",
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
  "prompt_bundle_revision_id": "00000000-0000-0000-0000-000000000011",
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
          "guest_name": {"type": "string", "minLength": 1, "description": "Name of the guest", "x-canonical-field": "guest.name"},
          "phone": {"type": "string", "minLength": 1, "description": "Guest phone number", "x-canonical-field": "guest.phone"},
          "check_in": {"type": "string", "format": "date", "description": "Arrival date", "x-canonical-field": "stay.check_in"},
          "check_out": {"type": "string", "format": "date", "description": "Departure date", "x-canonical-field": "stay.check_out"}
        },
        "required": ["guest_name", "phone", "check_in", "check_out"],
        "additionalProperties": false
      },
      "business_policy": {},
      "execution": {
        "plan_type": "google_sheets.append_values.v1",
        "connection_id": "00000000-0000-0000-0000-000000000021",
        "spreadsheet_id": "tenant-b-spreadsheet-id",
        "sheet_name": "Booking Requests",
        "append_range": "A:G",
        "value_input_option": "RAW",
        "idempotency": {"lookup_range": "A:A", "operation_id_column_index": 0},
        "request_mapping": "{\"rows\": [[metadata.operation_id, business.stay.check_in, business.stay.check_out, business.guest.name, business.guest.phone, \"new\", \"voice_agent\"]]}"
      },
      "validation_fixtures": [
        {"guest_name": "Fixture Guest", "phone": "+421900000000", "check_in": "2030-01-01", "check_out": "2030-01-02"},
        {"guest_name": "Fixture Guest", "phone": "+421900000001", "check_in": "2031-01-01", "check_out": "2031-01-02"}
      ]
    }
  }
}
```

Create the draft with `POST /admin/v1/tenants/{tenant_id}/config/drafts`, validate it with `POST .../{revision_id}/validate`, then publish it with `POST .../{revision_id}/publish`. Publication is local and has no Google side effect.

## Manual Google Sheet smoke test

1. Put the service-account map in the Job Worker secret environment and start PostgreSQL, Redis, Backend, Job Worker, LiveKit, and Voice Agent.
2. Create an active integration connection, create/validate/publish one of the configurations above, and start a new call so it pins that revision.
3. Invoke `reservation_submit_request` once and poll the returned invocation until terminal. Confirm the Sheet contains the operation ID and configured cells and the semantic result is `request_submitted`.
4. Re-deliver the same Redis job or retry after withholding the first Backend callback. Confirm the driver finds the operation ID and returns `deduplicated: true` without a normal second append.
5. Confirm Backend and Worker logs contain IDs and statuses but no guest fields, rows, credential references, or credentials.

The guarantee is at-least-once delivery plus Backend invocation uniqueness, one logical job ID, and provider lookup-before-append. Google Sheets does not provide an atomic lookup-and-append transaction, so two workers racing before either append can still create duplicate rows. The operation-ID column makes that residual race observable and repairable; this slice does not claim exactly-once delivery.
