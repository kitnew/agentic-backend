# Canonical Control Plane State

This directory contains Git-managed, human-editable authoring state. Executable
client code remains in `apps/control-plane`.

Supported canonical paths:

```text
platform/system_prompt.md
platform/profiles/<profile_key>.md
tenants/<tenant_slug>/tenant.yaml
tenants/<tenant_slug>/tenant_prompt.md
tenants/<tenant_slug>/knowledge/*.md
```

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
# edit control-plane/platform/system_prompt.md
agentctl system-prompt plan
agentctl system-prompt push
agentctl system-prompt publish

agentctl profile pull hotel_assistant
# edit control-plane/platform/profiles/hotel_assistant.md
# for a new key: agentctl profile create hotel_assistant
agentctl profile plan hotel_assistant
agentctl profile push hotel_assistant
agentctl profile publish hotel_assistant

agentctl tenant prompt pull penzion-grand
# edit control-plane/tenants/penzion-grand/tenant_prompt.md
agentctl tenant prompt plan penzion-grand
agentctl tenant prompt push penzion-grand
agentctl tenant prompt publish penzion-grand

agentctl tenant config pull penzion-grand
# edit control-plane/tenants/penzion-grand/tenant.yaml
agentctl tenant config plan penzion-grand
agentctl tenant config push penzion-grand
agentctl tenant config publish penzion-grand

agentctl tenant knowledge pull penzion-grand
# edit control-plane/tenants/penzion-grand/knowledge/*.md
agentctl tenant knowledge plan penzion-grand
agentctl tenant knowledge push penzion-grand
agentctl tenant knowledge publish penzion-grand
agentctl tenant prompt-set plan penzion-grand
agentctl tenant prompt-set apply penzion-grand
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
control-plane/
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
        ├── integrations.yaml
        └── capabilities.yaml
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
