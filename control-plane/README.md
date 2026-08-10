# Canonical Control Plane State

This directory contains Git-managed, human-editable authoring state. Executable
client code remains in `apps/control-plane`.

Supported canonical paths:

```text
platform/system_prompt.md
platform/profiles/<profile_key>.md
tenants/<tenant_slug>/tenant.yaml
tenants/<tenant_slug>/tenant_prompt.md
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
`tenant_prompt.md` contains tenant-specific behavioral instructions; and the
future `knowledge/` directory will contain factual/document sources. YAML uses
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

Future slices may extend this tree without changing these paths:

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
        ├── integrations.yaml
        └── capabilities.yaml
```

The `knowledge/` directory is reserved for a future document-oriented
KnowledgeBase workflow; this slice does not define a `knowledge.md` convention.
