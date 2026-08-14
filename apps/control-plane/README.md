# Agent Control Plane

`agentctl` is the command-line client for Backend Core's Admin API.

```bash
export AGENTCTL_API_URL=http://localhost:8000
export AGENTCTL_TOKEN=development-admin-token-change-me-now
export AGENTCTL_STATE_DIR=./definitions

uv run agentctl --help
uv run agentctl --version
uv run agentctl tenant list
uv run agentctl tenant create debug-hotel \
  --display-name "Debug Hotel" \
  --business-type hotel
uv run agentctl integration list penzion-grand
uv run agentctl system-prompt plan
uv run agentctl profile list
uv run agentctl sync plan
```

`--api-url` overrides `AGENTCTL_API_URL`. The token is accepted only through the
environment and is never printed. `--state-dir` overrides `AGENTCTL_STATE_DIR`;
the default canonical state root is `./definitions`.

Use `sync plan`, `sync push`, `sync publish`, and `sync pull [--force]` to
orchestrate the same resource workflows across the locally represented desired
state. Missing canonical resources are unmanaged; global sync never treats
absence as remote deletion and never creates remote tenants.

Create a tenant explicitly through the Admin API:

```bash
uv run agentctl tenant create debug-hotel \
  --display-name "Debug Hotel" \
  --business-type hotel
```

The command creates only the Backend tenant. It does not create or publish
tenant runtime/config files; add those under `definitions/tenants/<slug>/` and
use the corresponding `tenant config` or `tenant runtime` workflow afterward.
Use `--status suspended` or `--status archived` when a newly created tenant
must not be active immediately.

```bash
uv run agentctl system-prompt pull
# edit definitions/platform/system_prompt.md
uv run agentctl system-prompt plan
uv run agentctl system-prompt push
uv run agentctl system-prompt publish

uv run agentctl profile pull hotel_assistant
# for a new key with an existing canonical file:
# uv run agentctl profile create hotel_assistant
uv run agentctl profile plan hotel_assistant
uv run agentctl profile push hotel_assistant
uv run agentctl profile publish hotel_assistant

uv run agentctl tenant prompt pull penzion-grand
# edit definitions/tenants/penzion-grand/tenant_prompt.md
uv run agentctl tenant prompt plan penzion-grand
uv run agentctl tenant prompt push penzion-grand
uv run agentctl tenant prompt publish penzion-grand

uv run agentctl tenant knowledge pull penzion-grand
# edit definitions/tenants/penzion-grand/knowledge/*.md
uv run agentctl tenant knowledge plan penzion-grand
uv run agentctl tenant knowledge push penzion-grand
uv run agentctl tenant knowledge publish penzion-grand
uv run agentctl tenant prompt-set plan penzion-grand
uv run agentctl tenant prompt-set apply penzion-grand
```

TenantPrompt publication remains separate from PromptSet composition and
activation; publishing the artifact alone does not change runtime behavior.

## Integrations and post-call presets

Create and inspect tenant connection metadata by slug:

```bash
uv run agentctl integration create penzion-grand transcript_webhook \
  --provider managed_webhook \
  --credential-ref penzion-grand-transcript
uv run agentctl integration list penzion-grand
uv run agentctl integration show penzion-grand transcript_webhook
uv run agentctl integration delete penzion-grand transcript_webhook
```

These commands store only `key`, `provider`, and `credential_ref`. The referenced
URL/API key and hostname allowlist must still be provisioned in the Job Worker
deployment through mounted secrets and `/secrets/managed-webhooks.json`, selected
with `MANAGED_WEBHOOK_CONNECTION_MAP_FILE`. Credentials remain in the mounted
secret files.

Normal post-call authoring in `definitions/tenants/<slug>/tenant.yaml` is short:

```yaml
post_call_actions:
  - id: send_transcript
    connection: transcript_webhook
    preset: transcript.raw_json
  - id: send_recording
    connection: recording_webhook
    preset: recording.base64
```

Control Plane expands presets during plan/push. Use the documented advanced
JSONata action form only when the outbound payload must differ from the preset.

## Webhook capabilities

Webhook capabilities use the same short connection form. The Control Plane
resolves the integration key during `plan`/`push` and publishes only the strict
runtime execution contract:

```yaml
capabilities:
  reservation.submit_request:
    enabled: true
    description: Create a reservation request.
    announcement: I will send the reservation request now.
    type: http.post_json
    connection: reservation_webhook
    agent_input_schema:
      type: object
      additionalProperties: false
      required: [guest_name, check_in, check_out]
      properties:
        guest_name:
          type: string
          x-canonical-field: guest.name
        check_in:
          type: string
          format: date
          x-canonical-field: stay.check_in
        check_out:
          type: string
          format: date
          x-canonical-field: stay.check_out
    request_mapping: |
      {"guest_name": business.guest.name}
```

Do not write `connection_id`, `plan_type`, or JSONata engine/version metadata
in this form. `validation_fixtures` is optional for the standard reservation
input shape; add it when the Control Plane cannot derive a deterministic
fixture for your required fields. `business_policy.requires_final_confirmation`
and `business_policy.requires_caller_phone` remain explicit operator choices.

Knowledge authoring is a flat UTF-8 Markdown tree under
`tenants/<tenant_slug>/knowledge/*.md`. Filenames are stable document keys.
Publishing a KnowledgeBase snapshot does not activate it; explicit PromptSet
plan/apply selects it for new calls.
