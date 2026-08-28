# Declarative workspace

`definitions/` is the human-authored workspace consumed by `agentctl`.
Backend remains the authority for authoring validation, drafts, releases,
credentials, and runtime state.

```text
definitions/
├── platform/
│   ├── runtime.yaml
│   ├── system_prompt.md
│   └── profiles/<profile_key>.md
└── tenants/<tenant_slug>/
    ├── tenant.yaml
    ├── runtime.yaml
    ├── tenant_prompt.md
    ├── capabilities.yaml
    ├── post_call.yaml
    └── knowledge/knowledge.md
```

`tenant.yaml` is the local projection of the tenant Agent component and is the
place for handoff destinations. Tenant Telephony is a remote-only component;
its `phone_number` is managed with `agentctl did` and is not added to the
workspace tree.

## Workspace lifecycle

```bash
agentctl status
agentctl pull
agentctl plan
agentctl push
agentctl publish
```

The commands operate on Platform and every tenant returned by Backend. Narrow
the same workflow explicitly when needed:

```bash
agentctl status platform
agentctl pull tenant hotel
agentctl plan tenant hotel
agentctl push tenant hotel
agentctl publish tenant hotel
```

`status` is read-only. `pull` performs a global preflight before writing any
projection. `plan` calls Backend authoring plan endpoints without persistence.
`push` saves drafts with existing ETag/CAS semantics and never publishes.
`publish` performs a global preflight, then delegates Platform Publish All once
and Tenant Publish All once per selected tenant. A remote Telephony draft is
included by Backend tenant publication but is not locally projected.

The normal onboarding cycle is:

```text
agentctl tenant create hotel --display-name "Hotel" --business-type hotel
→ agentctl pull tenant hotel
→ edit handoff in definitions/tenants/hotel/tenant.yaml
→ agentctl status tenant hotel
→ agentctl plan tenant hotel
→ agentctl push tenant hotel
→ agentctl did assign hotel +421551234567
→ agentctl publish tenant hotel
```

Local files contain operator authoring values only. Do not add revision IDs,
ETags, connection UUIDs, runtime plan metadata, credential material, or
provider implementation details. Prompt files contain text only. Knowledge is
human-authored content, not database artifact metadata.

## Tenant identity and operational facades

```bash
agentctl tenant list
agentctl tenant show hotel
agentctl tenant create hotel --display-name "Hotel" --business-type hotel

agentctl integration list hotel
agentctl integration show hotel check-availability
agentctl did show hotel
```

Integration and DID commands have live/operational lifecycles and are not part
of local workspace synchronization. DID changes are saved as a remote
Telephony draft and included in Tenant Publish All when the tenant is
published. Handoff remains in the local Agent projection (`tenant.yaml`).

Platform `system-prompt`, `runtime`, and `profile` commands remain read-only
inspection paths for active values, revisions, and profile listings. Workspace
mutation is available only through the five lifecycle commands above.
