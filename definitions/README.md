# Declarative Platform Definitions

This directory contains Git-managed, human-editable authoring state. Executable
client code remains in `apps/control-plane`.

Supported canonical paths:

```text
platform/system_prompt.md
platform/runtime.yaml
platform/profiles/<profile_key>.md
tenants/<tenant_slug>/tenant.yaml
tenants/<tenant_slug>/tenant_prompt.md
tenants/<tenant_slug>/runtime.yaml
tenants/<tenant_slug>/knowledge/*.md
```

Global reconciliation uses only paths already represented in this checkout:

```bash
agentctl sync plan
agentctl sync push
agentctl sync publish
agentctl sync pull [--force]
```

Presence is the management marker. A missing `system_prompt.md`, profile file,
`tenant.yaml`, `tenant_prompt.md`, `runtime.yaml`, or `knowledge/` directory is
unmanaged and is never a remote deletion request. A present empty tenant
`runtime.yaml` mapping (`{}`) explicitly manages an empty override. A present
`knowledge/` directory is the full managed document snapshot, including when it
is empty. Remote-only profiles and tenants are not pulled, changed, or
materialized by global pull.

`sync plan` is read-only. `sync push` changes drafts only. `sync publish` first
checks the complete managed state against remote drafts, then publishes in
dependency order and asks Backend to reconcile the independent VoiceRuntime and
PromptSet dimensions for local tenant directories. `sync pull` compares every
managed authoring resource before writing; without `--force`, one conflict
prevents all writes. Derived runtime snapshots, revision IDs, ETags, timestamps,
and secrets are never written to this directory.

Markdown files contain prompt text only. Revision IDs, versions, status, and
timestamps remain in Backend Core/PostgreSQL. The canonical SystemPrompt uses
the stable platform key `default`; Backend runtime activation still happens only
through explicit PromptSet revision references.

No canonical prompt text was added initially because the repository contains
only tenant-specific migrated `legacy_*` SystemPrompts and an empty
`legacy_default` ProfilePrompt. Pull an existing published resource rather than
synthesizing prompt prose.

```bash
agentctl system-prompt pull
# edit definitions/platform/system_prompt.md
agentctl system-prompt plan
agentctl system-prompt push
agentctl system-prompt publish

agentctl profile pull hotel_assistant
# edit definitions/platform/profiles/hotel_assistant.md
# for a new key: agentctl profile create hotel_assistant
agentctl profile plan hotel_assistant
agentctl profile push hotel_assistant
agentctl profile publish hotel_assistant

agentctl tenant prompt pull penzion-grand
# edit definitions/tenants/penzion-grand/tenant_prompt.md
agentctl tenant prompt plan penzion-grand
agentctl tenant prompt push penzion-grand
agentctl tenant prompt publish penzion-grand

agentctl tenant config pull penzion-grand
# edit definitions/tenants/penzion-grand/tenant.yaml
agentctl tenant config plan penzion-grand
agentctl tenant config push penzion-grand
agentctl tenant config publish penzion-grand

agentctl tenant knowledge pull penzion-grand
# edit definitions/tenants/penzion-grand/knowledge/*.md
agentctl tenant knowledge plan penzion-grand
agentctl tenant knowledge push penzion-grand
agentctl tenant knowledge publish penzion-grand
agentctl tenant prompt-set plan penzion-grand
agentctl tenant prompt-set apply penzion-grand

agentctl runtime pull
# edit definitions/platform/runtime.yaml
agentctl runtime plan
agentctl runtime push
agentctl runtime publish

agentctl tenant runtime pull penzion-grand
# edit definitions/tenants/penzion-grand/runtime.yaml
agentctl tenant runtime plan penzion-grand
agentctl tenant runtime push penzion-grand
agentctl tenant runtime publish penzion-grand
agentctl tenant voice-runtime plan penzion-grand
agentctl tenant voice-runtime apply penzion-grand
```

`pull` creates parent directories and refuses to overwrite differing local
content unless `--force` is supplied. `push` writes only a remote draft;
`publish` is always a separate explicit command. Starting Backend Core or
`agentctl` never synchronizes files.

`tenant_prompt.md` is the canonical successor to legacy tenant-specific
`instructions.md` content. It contains behavioral/conversational prose only;
deterministic tenant data belongs in future TenantConfig, factual sources in
KnowledgeBase, connection metadata in integrations/capability bindings, and
credentials in secrets. Publishing a TenantPrompt revision does not activate
it: a separately published PromptSet must reference that revision.

`tenant.yaml` contains structured deterministic TenantConfig data;
`tenant_prompt.md` contains tenant-specific behavioral instructions; and
`knowledge/*.md` contains factual source documents. YAML uses
the current explicit `schema_version: 3`, stable model-field ordering, two-space
indentation, Unicode text, block style, sorted free-form capability mappings,
and one final newline. Mapping order and formatting do not affect comparison.
An explicit `pull --force` writes canonical formatting and does not preserve
comments. TenantConfig schema migrations are never implicit: historical V1/V2/V3
revisions remain immutable and a future V4 will require an explicit migration
workflow.

`tenant config push` writes and validates only a draft. `tenant config publish`
activates that revision for new calls according to Backend semantics; existing
calls remain pinned to the revision with which they started. It does not alter
PromptSet state.

## Post-call actions

Create connection metadata once. `agentctl` resolves the tenant slug; the
credential reference is not a secret:

```bash
agentctl integration create penzion-grand transcript_webhook \
  --provider managed_webhook \
  --credential-ref penzion-grand-transcript
agentctl integration create penzion-grand recording_webhook \
  --provider managed_webhook \
  --credential-ref penzion-grand-recording
```

Provision each referenced webhook URL/API key separately in the deployment's
mounted secrets and `/secrets/managed-webhooks.json`. `agentctl integration`
manages Backend metadata only; it never reads or writes deployment secrets.

Normal `tenant.yaml` authoring uses platform-owned presets:

```yaml
post_call_actions:
  - id: send_transcript
    connection: transcript_webhook
    preset: transcript.raw_json

  - id: send_recording
    connection: recording_webhook
    preset: recording.base64
```

Then validate and publish the pinned runtime revision:

```bash
agentctl tenant config plan penzion-grand
agentctl tenant config push penzion-grand
agentctl tenant config publish penzion-grand
```

The only supported presets are `transcript.raw_json` and `recording.base64`.
Control Plane expands them into strict artifact inputs and the standard HTTP
payload mapping. Backend never receives the `preset` or connection alias.

For a custom payload, use the advanced bounded JSONata form instead of a
preset:

```yaml
post_call_actions:
  - id: custom_delivery
    type: http.post_json
    connection: crm_webhook
    inputs:
      transcript:
        artifact: transcript
        representation: raw_json
    request_mapping: |
      {
        "call_id": call_id,
        "conversation": inputs.transcript.value
      }
    timeout_seconds: 10
```

`agentctl tenant config plan`, `push`, and global `sync` compile this into the
pinned runtime revision: `id` becomes the stable action identity,
`connection` becomes its managed connection ID, and the generic HTTP/JSONata
execution contract is filled by the platform. Runtime-only execution metadata
and connection IDs do not belong in `tenant.yaml`.

Preset and advanced fields cannot be mixed. JSONata maps bounded JSON only and
is not required in preset authoring. Each advanced structured input is
available as `inputs.<name>.value`. A body-capable representation is always
available as `inputs.<name>.body`, independent of its size; for example,
`call_recording/base64_text` is streamed to the generic HTTP executor rather
than entering JSONata or Redis. The mapping selects where that body is placed
in the outbound JSON; it cannot define scheduling, retries, conditions, or
workflow dependencies.

## Voice runtime policy

`platform/runtime.yaml` is a complete logical runtime policy. It contains no
credentials, endpoint, Azure deployment name, or provider reliability timeout:

```yaml
llm:
  provider: azure_openai
  model: <logical-model-key>
  temperature: 0.0
stt:
  provider: elevenlabs
  model: scribe_v2_realtime
  server_vad:
    silence_threshold_seconds: 0.5
    activity_threshold: 0.35
    min_speech_ms: 100
    min_silence_ms: 500
tts:
  provider: elevenlabs
  model: eleven_flash_v2_5
  voice_id: <truthful-default-elevenlabs-voice-id>
local_vad:
  min_speech_seconds: 0.05
  min_silence_seconds: 0.25
  activation_threshold: 0.5
turn:
  detection: stt
  min_endpointing_delay_seconds: 0.1
  max_endpointing_delay_seconds: 0.7
```

The only tenant override in this slice is either an explicit voice:

```yaml
tts:
  voice_id: <tenant-elevenlabs-voice-id>
```

or `{}` to reset effective behavior to the platform voice. Runtime publication
never activates tenants. Backend resolves the latest published platform policy,
latest published tenant override (if any), and active TenantConfig locale only
when `tenant voice-runtime apply` runs. Equal behavior is a no-op; changed
behavior always creates the next immutable revision, including A to B to A.
New calls pin that active revision alongside TenantConfig and PromptSet.

The repository intentionally does not ship an initial runtime file: neither the
truthful Azure logical model key nor the current ElevenLabs voice ID can be
derived from source. Deployment cutover is explicit:

```bash
# 1. deploy schema and code
# 2. create platform/runtime.yaml with truthful non-secret values
# 3. optionally create tenants/debug-hotel/runtime.yaml
uv run agentctl sync plan
uv run agentctl sync push
uv run agentctl sync plan
uv run agentctl sync publish
uv run agentctl sync plan
uv run agentctl tenant voice-runtime show debug-hotel
uv run agentctl tenant voice-runtime revisions debug-hotel
```

Verify an E2E call only after `debug-hotel` has an active VoiceRuntime. The call
must contain config, PromptSet, and VoiceRuntime revision IDs. To verify dynamic
voice rollout, publish a changed tenant `tts.voice_id`, apply VoiceRuntime, and
place a new call without restarting Voice Agent; the old call stays pinned.

Current authoring shape:

```yaml
schema_version: 3
business:
  name: Penzión Grand
  type: hotel
contact:
  address: null
  phones:
    - "+421900000000"
  emails:
    - info@example.com
  website: null
localization:
  default_locale: sk-SK
  timezone: Europe/Bratislava
agent:
  display_name: Amélia
  greeting: Dobrý deň
  profile: hotel_assistant
conversation:
  scope: property_only
capabilities: {}
```

Canonical authoring uses a flat Markdown-only knowledge directory:

```text
definitions/
├── platform/
│   ├── system_prompt.md
│   ├── profiles/
│   │   └── hotel_assistant.md
│   └── runtime.yaml
└── tenants/
    └── <tenant_slug>/
        ├── tenant.yaml
        ├── tenant_prompt.md
        ├── knowledge/
        │   ├── knowledge.md
        │   ├── rooms.md
        │   └── policies.md
        └── runtime.yaml
```

Each filename must match `<key>.md`, where the key begins with a lowercase
letter and contains only lowercase letters, digits, `_`, or `-`. Subdirectories,
symlinks, hidden files, and non-Markdown files are rejected. Content is preserved
as UTF-8 Markdown; comments are ordinary document content.

`knowledge pull` materializes the latest published snapshot and refuses any
local document-set difference unless `--force` is supplied. A forced pull
overwrites managed Markdown files and removes managed local-only Markdown files,
but never deletes unsupported files. Removing or renaming a local Markdown file
only removes the old logical document from the next snapshot; historical
snapshots and immutable document revisions remain reproducible. Rename detection
and garbage collection are intentionally absent.

`knowledge push` reconciles the full local document set into a remote draft and
reuses unchanged document revisions. `knowledge publish` publishes that snapshot
but does not activate it. Run `tenant prompt-set plan` and explicit
`tenant prompt-set apply` to select the newest published KnowledgeBase for new
calls. Existing calls remain pinned to their original PromptSet and KB snapshot.
Future RAG processing will attach to the immutable document revisions allowed by
that pinned KB snapshot; this workflow does not implement retrieval, chunks, or
embeddings.
