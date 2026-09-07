# Current → Target Gap Analysis

## 1. Executive summary

The repository is materially behind the frozen target architecture. It has a substantial legacy Control Plane foundation—versioned components, encrypted credentials, provider/deployment resources, runtime resolution, immutable snapshot persistence, internal service authentication, and an outbox—but these pieces are organized around low-level lifecycle APIs and `ExecutionSnapshot` transport rather than the target semantic configuration and consumer-projection model.

Strongest aligned areas:

- Versioned component draft/publish/history persistence.
- Component schema and allowed-scope registry.
- Encrypted credential versions with rotation/revocation.
- Provider/deployment and telephony resource models.
- Repeatable-read snapshot creation.
- Late-bound runtime secret material.
- Separate management and service authentication primitives.
- Generated OpenAPI/client tooling exists.

Largest mismatches:

- No `LiveComponent` primitive; runtime live state is stored as versioned components.
- No high-level `SystemConfigurationService`, `PlatformConfigurationService`, or `TenantConfigurationService`.
- Catalogs are absent.
- Registry coverage is incomplete and partly hard-coded.
- Current HTTP management API is under unscoped `/v1/*`.
- Internal APIs expose raw `ExecutionSnapshot` and persistence-oriented IDs.
- Backend reconstructs consumer context from raw snapshot data.
- Consumer contracts expose `ComponentAddress`, revisions, generations, and provider/resource structures.
- No Control Plane idempotency implementation was found.
- Current transaction ownership is primarily repository-level rather than semantic application-use-case-level.
- No target-wide `ErrorResponse` / `ValidationIssue` contract.
- Current schemas contain legacy runtime/capability/post-call concepts not represented directly in the frozen target inventory.

The databases are empty, so schema replacement is preferable to compatibility layers or persistent-data migration. Consumer and client code still requires coordinated contract migration.

## 2. Current architecture map

The current Control Plane contains:

- A generic versioned component model with one component address, one mutable draft, active revisions, revision history, rollback provenance, and schema registry.
- Runtime-specific component registrations such as `runtime.llm.defaults`, `runtime.stt.defaults`, `runtime.tts.defaults`, `runtime.cascade.execution.defaults`, `runtime.realtime.execution.defaults`, `runtime.architecture.policy`, and `runtime.speech.overrides`.
- Managed resources for credentials, provider connections, model deployments, integrations, handoff destinations, and phone assignments.
- A `RuntimeResolver` that loads current component/resource state and resolves a runtime candidate.
- An `ExecutionSnapshotService` that persists resolved state in `execution_snapshots`.
- An `ExecutionMaterializationService` that later decrypts secrets and materializes integration/handoff data.
- Low-level HTTP routes under `/v1/scopes/*` and `/v1/managed-resources/*`.
- Internal routes under `/internal/v1/*`, but with snapshot-oriented paths and raw snapshot responses.
- NATS/outbox publication for component and managed-resource events.

Backend directly depends on the Control Plane client for:

- phone resolution;
- snapshot creation;
- raw snapshot reads;
- handoff material;
- integration material.

Backend then parses the raw snapshot into `VoiceAgentRuntimeContext`. Voice Agent receives that Backend-derived context and directly calls Control Plane for runtime secrets. Worker calls Backend for integration material and does not directly call Control Plane, but current jobs carry `execution_snapshot_id`.

`agentctl` directly calls low-level Control Plane component and managed-resource routes. Admin Web directly consumes generated low-level Control Plane APIs through a Vite proxy that rewrites `/control-plane/*` to `/v1/*`.

The following relationship is a Codex inference from those call sites: the current runtime path is effectively:

```text
Backend → Control Plane raw snapshot
Backend → reconstructs runtime context
Backend → Voice Agent
Voice Agent → Control Plane secret endpoint

Worker → Backend → Control Plane integration material
```

This differs from the target flow:

```text
resolve effective state
→ persist immutable snapshot
→ derive consumer projections
→ late-bind secret/material resources
```

## 3. Gap matrix

| Area | Current state + evidence | Target requirement | Classification | Gap | Affected consumers/files | Notes / risk |
|---|---|---|---|---|---|---|
| Core component primitive | `ComponentAddress`, `ComponentDraft`, `ComponentRevision`, `ComponentSnapshot` exist in `domain/components/model.py:62-113` | Five primitives only: VersionedComponent, LiveComponent, ManagedResource, Catalog, Registry | MODIFY | Current versioned primitive is reusable, but no live primitive exists | Control Plane domain, persistence, all management clients | Core lifecycle distinction is foundational |
| Versioned lifecycle | `ComponentService.save_draft`, `publish_draft`, `rollback` in `application/components.py:32-79` | Draft, immutable revisions, explicit publish/discard/rollback with provenance | KEEP/MODIFY | Semantics mostly aligned; public IDs/body versions and scope routes are not | CP, agentctl, Admin Web | Preserve domain behavior, replace transport |
| Schema registry | `ComponentDefinition` and `ComponentRegistry` in `domain/components/registry.py:12-55` | `ComponentDefinitionRegistry` owns schema/version/scope validation | MODIFY | Current role is aligned but naming/coverage/transport exposure need target alignment | CP domain, registry API | Existing registry should be reused rather than duplicated |
| Live components | Runtime values are registered through `ComponentDefinition` and persisted in component revisions, e.g. `runtime.llm.defaults` in `domain/runtime_components.py:208-257` | Exactly one current value, immediate activation, no draft/history/publish | REPLACE | Versioned persistence is semantically wrong for system and tenant live state | Runtime resolver, CP persistence, Admin Web, agentctl | Highest-risk lifecycle mismatch |
| System configuration | No `SystemConfigurationService`; only low-level `ComponentService` exists | Atomic get/plan/apply over five system live components | ADD | Missing semantic aggregate and atomic application service | CP, agentctl, Admin Web | Current callers must stop orchestrating components |
| Platform configuration | No platform configuration service/catalog persistence found | Atomic catalog apply plus prompt drafts and atomic publish | ADD | Missing high-level service and catalogs | CP, agentctl, Admin Web | Prompt/catalog lifecycle must remain separate |
| Tenant configuration | No tenant configuration service found | Atomic mixed live apply and versioned draft apply/publish | ADD | Missing semantic aggregate, cross-object validation, and atomic mixed lifecycle | CP, Backend, agentctl, Admin Web | Major cross-domain dependency |
| Catalogs | No `ProfileCatalog` or `InteractionModeCatalog` persistence/domain object found | Operator-managed stable-key catalogs | ADD | Profiles/interaction modes are implicit or represented as component scope keys | CP, Admin Web, agentctl, tenant configuration | Prompt lifecycle must not be merged into catalog CRUD |
| Architecture registry | `ArchitectureKind = Literal["cascade", "realtime"]` in `domain/runtime_components.py:140`; `ArchitecturePolicy` stores an allowlist | Read-only `ArchitectureRegistry`; values resolve through it | MODIFY | Hard-coded literal replaces registry semantics; `half-cascade` is absent | Runtime resolver, tenant configuration | Target requires registry validation |
| Provider registry | `ProviderRegistry` exists and validates provider/deployment configuration | `ProviderKindRegistry` and `DeploymentKindRegistry` | MODIFY | Provider registry exists, but deployment-kind validation and registry API are not target-shaped | Provider service, CP API | Existing validation is useful |
| Integration registry | Integrations are restricted to HTTP by DB constraint and HTTP-specific service logic | Read-only `IntegrationKindRegistry` | REPLACE/MODIFY | Current implementation hard-codes only `http` rather than registry-driven kinds | Managed resources, Worker, Backend | Target explicitly reserves multiple integration kinds |
| Managed resources | Credential, provider, deployment, integration, handoff, and phone assignment models exist | Independent managed-resource lifecycles | MODIFY | Good resource boundary, but scopes, routes, DTOs, ETags, and validation semantics differ | CP, all management clients | Reuse domain intent; replace contracts where needed |
| Credential scope | `Credential` has no platform/tenant scope field in `domain/managed_resources.py:69-80` and persistence `models.py:139-171` | Platform- or tenant-scoped credentials with immutable scope | REPLACE/MODIFY | Scope/ownership cannot currently be represented | Providers, integrations, management API | Security and reference validation risk |
| Credential secrets | `CredentialVersion` stores nonce/ciphertext/key metadata; `CredentialCipher` decrypts only in materialization | Encrypted storage, immutable versions, normal reads exclude secrets, late binding | KEEP/MODIFY | Strong alignment; transport currently returns resource metadata including generations/version IDs | CP, Backend, Voice Agent, Worker | Secret isolation is one of the strongest current areas |
| Provider/deployment graph | Provider connections reference credentials; deployments reference connections in `models.py:207-353` | Registry-validated provider graph with credential references and enable/disable | MODIFY | Resource shape aligns, but validation, scope, ETags, and external validation boundary need change | CP, runtime resolver | Raw graph leaks into snapshot/runtime |
| Telephony | Phone normalization and uniqueness indexes exist in `models.py:291-324`; service normalizes in `managed_resources.py:359-385` | Tenant-owned assignments, normalized phone identity, semantic inbound route | MODIFY | Internal endpoint returns assignment ID and generation rather than `InboundRoute` with opaque route version | Backend, CP | Current extra per-tenant uniqueness constraint may be target-silent |
| Integrations | Only HTTP connections supported; tenant ID is in create body; material uses connection ID | Tenant-scoped semantic integration keys, registry validation, late-bound material | MODIFY/MIGRATE | Route ownership and material contract differ; consumer receives raw connection identifiers/generations | Backend, Worker, agentctl, Admin Web | Requires coordinated consumer migration |
| Handoff | Tenant-owned keyed destinations exist with generation and enable/disable | Tenant-owned handoff resources and semantic handoff material | MODIFY | Current material path is snapshot-based and body uses destination key; target uses execution ID and destination key path | Backend, Voice Agent | Snapshot tenant binding must remain enforced |
| Execution snapshot | Immutable dataclass and DB row exist in `runtime_execution_snapshot.py:57-68`, `models.py:356-376` | Internal immutable persistence artifact, never raw transport | KEEP/MODIFY | Persistence seam exists; transport and downstream usage expose raw snapshot | CP, Backend, Voice Agent, Worker, contracts | Current snapshot implementation is a useful base |
| Snapshot creation | `ExecutionSnapshotService.materialize` uses `REPEATABLE READ` and writes one row in `runtime_materialization.py:39-92` | Resolve, validate, persist one complete immutable snapshot atomically | KEEP/MODIFY | Repeatable-read/all-or-nothing shape aligns; service still exposes materialize terminology and old resolver split | CP, Backend | Need consumer projections and opaque execution handle |
| Snapshot re-resolution | `get_snapshot` reads by ID in `runtime_materialization.py:94-98`; Backend re-reads raw snapshot in `execution_context.py:29-93` | Existing snapshot is never silently re-resolved | KEEP/MODIFY | Reads are immutable, but Backend interprets snapshot internals rather than receiving projections | Backend, Voice Agent | Need explicit projection APIs |
| Consumer projection | No `BackendExecutionContext`, `VoiceExecutionContext`, or `WorkerExecutionContext` endpoint was found | Projection endpoints derived from same snapshot | ADD/MIGRATE | Current raw snapshot is the de facto projection source | Backend, Voice Agent, Worker | Critical topology gap |
| Runtime secret material | `ExecutionMaterializationService.runtime_secret` late-binds active credential in `execution_materialization.py:80-111` | Dedicated `RuntimeSecretMaterial` containing only slot/secret | MODIFY | Current response includes snapshot/resource provenance fields and uses `snapshot_id` | Voice Agent, CP | Late binding is aligned; DTO is overexposed |
| Backend topology | Backend calls raw snapshot APIs and reconstructs context in `platform/control_plane.py:26-40` and `runtime/execution_context.py:29-85` | Backend obtains semantic projections and material through internal API | MIGRATE | Backend depends on raw persistence terminology and graph structure | Backend | Contract-breaking change required |
| Voice Agent topology | Voice Agent receives Backend context but directly calls `/internal/v1/execution-snapshots/{snapshot_id}/secrets/{slot}` in `voice_agent/backend.py:113-130` | Direct CP access only for explicitly authorized late-bound runtime secrets | MODIFY | Permission shape is aligned, but endpoint and execution identifier are not | Voice Agent | Direct dependency may remain narrowly |
| Worker topology | Worker calls Backend integration material endpoint and has no CP client; `worker.py:1003-1025` | No direct CP dependency; Backend passthrough | MODIFY/MIGRATE | Topology is aligned, but jobs use `execution_snapshot_id` and current integration material has raw IDs/generations | Worker, Backend, contracts | No Worker credentials should be added |
| Management HTTP | Routes are `/v1/scopes/*` and `/v1/managed-resources/*` in `interfaces/http/app.py:313-321` | `/management/v1/*` only | REPLACE | Namespace and route structure conflict | agentctl, Admin Web, OpenAPI | Do not preserve old routes |
| Internal HTTP | Snapshot endpoints use `/internal/v1/execution-snapshots/*`; telephony returns raw assignment records | `/internal/v1/executions/{execution_id}/*` semantic operations | REPLACE/MODIFY | Persistence terminology and raw DTOs leak | Backend, Voice Agent, Worker | Requires coordinated deployment |
| High-level API | No configuration endpoints or services found | System/platform/tenant get/plan/apply/publish endpoints | ADD | Entire primary operator surface is missing | agentctl, Admin Web | Existing low-level API is not an adequate substitute |
| DTO boundary | `SaveDraftRequest` includes `schema_version`, `expected_draft_version`, `expected_active_revision_id` in `app.py:69-82`; runtime context includes `snapshot_runtime` and revision ID in `execution_context.py:64-83` | Semantic DTOs; lifecycle internals hidden from high-level and runtime contracts | REPLACE/MODIFY | Current DTOs expose internal lifecycle and snapshot data | All consumers | Generated schemas must be regenerated from new API |
| Concurrency | Current APIs use body/query `expected_draft_version` and `expected_generation`; client converts ETag to numeric versions in `admin-web/src/core/configuration/control-plane.tsx:52-105` | Opaque ETag/If-Match, stale state → 412 | REPLACE/MODIFY | ETag is cosmetic while domain-specific numeric tokens remain contract fields | CP, agentctl, Admin Web | Do not retain numeric fields for compatibility |
| Idempotency | No Control Plane `Idempotency-Key` handling or replay table was found in scoped Control Plane code; Backend has separate call idempotency in `calls/service.py:331-389` | Atomic lookup/replay/mutation record for required CP mutations | ADD | Required CP idempotency is absent | CP, all management clients, Backend execution creation | Must cover execution creation and retry-sensitive mutations |
| Transactions | `ComponentService` delegates to repository; repository transaction helper appears in `infrastructure/persistence/repository.py:64-71`; managed service delegates similarly | Application services own semantic transaction boundaries | MODIFY | Repository-level transaction ownership does not establish multi-object atomic configuration operations | CP application/persistence layers | External validation must remain outside DB transactions |
| Authorization | Separate `ManagementPrincipal` and `ServicePrincipal` exist in `service_auth.py:26-36`; service scopes are enumerated at lines 14-20 | Separate management/internal auth boundaries with precise scopes | MODIFY | Primitive exists, but management routes are unscoped `/v1/*`; current service scopes are snapshot/resource-specific rather than target semantic operations | CP, Backend, Voice Agent, Worker | Backend must not receive management privileges |
| Error model | Handlers return `{"detail": {"code": ..., "message": ...}}` in `app.py:241-287`; runtime errors include ad hoc details/attempts | Shared `ErrorResponse` and `ValidationIssue` with stable status semantics | REPLACE/MODIFY | No frozen shared error DTO is implemented | CP, clients, OpenAPI | Must distinguish 409/412/422 |
| OpenAPI | Export scripts exist: `scripts/export_control_plane_openapi.py:11-74`; generated snapshots contain `/v1/*` and raw snapshot routes | OpenAPI is machine-readable source of truth for target contract | MODIFY | Generation machinery exists, but exported contract is the legacy API | Admin Web, agentctl, shared clients | Regenerate after target contract change |
| Admin Web | Proxy rewrites `/control-plane` to `/v1` and injects management token in `vite.config.ts:35-47`; UI calls generated low-level component APIs | Normal workflows use high-level management API | MIGRATE | Browser is coupled to legacy route names and low-level lifecycle | Admin Web | Existing proxy mechanism can be replaced independently |
| agentctl | `ControlPlaneClient` constructs `/v1/scopes/*` and `/v1/managed-resources/*`; sends expected versions in bodies at `agentctl/control_plane.py:45-177` | High-level semantic workflows; low-level APIs only for expert operations | MIGRATE | CLI workspace orchestration is component-oriented and client parses ETags as integer draft versions | agentctl | Must migrate workspace semantics, not preserve routes |
| Outbox/NATS | CP has outbox rows and JetStream relay; CP README lines 14-28 documents event publication | Target documents transactional guarantees but does not freeze event taxonomy/transport | TARGET-SILENT/MODIFY | Existing event behavior has no explicit target fate | CP, any event consumers | Requires explicit decision before implementation |
| Legacy runtime components | `agent`, `knowledge`, `capabilities`, `post_call`, runtime policy components are registered separately | Target inventory names tenant semantic components and treats Actions as aggregate | REPLACE/MIGRATE/TARGET-SILENT | Several current components do not map one-to-one to target objects | Runtime resolver, Backend, Worker, agentctl | Do not invent mappings silently |

## 4. Detailed findings by architecture area

### A. Fundamental building blocks

**Repository fact:** The current domain defines a generic component address, drafts, revisions, and snapshots, but no `LiveComponent`, `Catalog`, or generic `ManagedResource` domain primitive.

**Evidence:** `apps/control-plane-service/src/control_plane/domain/components/model.py:62-113`; `domain/managed_resources.py:9-187`; `domain/components/registry.py:12-55`.

**Target:** The target limits fundamental building blocks to `VersionedComponent`, `LiveComponent`, `ManagedResource`, `Catalog`, and `Registry`. Configuration aggregates are semantic views, not another generic lifecycle primitive.

**Classification:** MODIFY / ADD / REPLACE.

**Gap:** The current versioned component machinery is reusable. Runtime and tenant live state must move to a distinct live persistence/lifecycle model. Catalogs must be added. Existing generic snapshot/configuration abstractions must not become competing primitives.

**Affected code/consumers:** Control Plane domain, repositories, persistence, runtime resolver, Admin Web, agentctl.

**Missing evidence / uncertainty:** The target does not specify the exact class/module names or database table names for the five primitives.

### B. VersionedComponent

**Repository fact:** Current versioned components have stable address data, one draft, immutable revision rows, revision numbers, `based_on_revision_id`, rollback provenance, and registry validation.

**Evidence:** `domain/components/model.py:62-113`; `application/components.py:32-79`; migration `0001_initial_control_plane.py:20-139`.

**Target:** Stable `(kind, scope)` identity, one mutable draft, immutable published revisions, append-only history, explicit publish/discard/rollback, provenance, schema registry, allowed scopes, optimistic concurrency.

**Classification:** KEEP/MODIFY.

**Gap:** Domain semantics are substantially aligned. Current draft schema version is client-supplied through `SaveDraftRequest`, while the target says schema ownership belongs to `ComponentDefinitionRegistry`. Current transport exposes draft versions and revision IDs, while target transport uses ETags and semantic revision DTOs.

**Affected code/consumers:** `app.py:69-82`, `agentctl/control_plane.py:85-174`, Admin Web control-plane hooks.

### C. LiveComponent

**Repository fact:** Runtime configuration types such as `LLMDefaults`, `STTDefaults`, `TTSDefaults`, `RealtimeExecutionDefaults`, and tenant runtime policies are registered as ordinary `ComponentDefinition` instances and flow through versioned component storage.

**Evidence:** `domain/runtime_components.py:208-257`; `application/runtime_resolver.py:61-87`.

**Target:** One current value, immediate activation, optimistic concurrency, no draft, revision history, publish, or rollback.

**Classification:** REPLACE.

**Gap:** Current runtime configuration has versioned lifecycle semantics even where target explicitly requires live lifecycle semantics. This affects system defaults and tenant `Architecture`, `ProfileReference`, `RuntimeOverrides`, and `ActionsAvailability`.

**Affected code/consumers:** Runtime resolver, component repository, migration schema, Admin Web, agentctl, execution materialization.

### D. Catalogs and Registries

**Repository fact:** No catalog persistence/domain objects for profiles or interaction modes were found. Profile-like behavior currently appears through `ProfileScope` and `prompt.profile` registration. Architecture is a `Literal`; integration persistence is constrained to `http`.

**Evidence:** `domain/components/model.py:45-57`; `domain/prompt_components.py:44-58`; `domain/runtime_components.py:140-155`; `models.py:233-244`.

**Target:** Add `ProfileCatalog`, `InteractionModeCatalog`, and read-only registries for architecture, component definitions, provider kinds, deployment kinds, and integration kinds.

**Classification:** ADD/MODIFY.

**Gap:** Catalog entries and associated prompt components are not modeled as separate lifecycle concerns. Registry-driven validation is incomplete and partly hard-coded.

**Affected code/consumers:** Tenant configuration, platform configuration, low-level registry endpoints, runtime resolver, Admin Web, agentctl.

**Missing evidence / uncertainty:** The target does not freeze whether catalogs eventually support archival in addition to enable/disable; `CONTRACTS.md:1789-1804` marks this target-silent.

### E. Managed resource domains

#### Credentials

**Repository fact:** Credentials have independent IDs, status, generation, active version, encrypted credential-version storage, and revoke/rotate operations.

**Evidence:** `domain/managed_resources.py:69-91`; `models.py:139-205`; `application/execution_materialization.py:192-218`.

**Target:** Credentials are scoped managed resources with immutable secret versions, encrypted storage, normal reads excluding secrets, rotation, revocation, and late-bound use.

**Classification:** KEEP/MODIFY.

**Gap:** Credential scope is not represented. Normal resource DTOs expose generation/version metadata that should be internal. Current rotation/revocation has no Control Plane idempotency contract.

#### Providers

**Repository fact:** Provider connections reference credentials; deployments reference provider connections and carry deployment kind/capability metadata.

**Evidence:** `domain/managed_resources.py:93-140`; `models.py:207-353`; `application/managed_resources.py:202-247` and `427-489`.

**Target:** `ProviderConnection` and `ModelDeployment` are managed resources validated through provider/deployment registries, with enable/disable and external validation outside database transactions.

**Classification:** MODIFY.

**Gap:** Existing shapes are useful, but provider/deployment registry exposure, credential scope checks, ETag transport, and external validation boundaries require change. Raw graph details must not enter runtime contexts.

#### Telephony

**Repository fact:** Phone numbers are normalized before create/update; database indexes enforce unique enabled phone numbers and unique enabled tenant assignment.

**Evidence:** `domain/managed_resources.py:183-187`; `application/managed_resources.py:359-385`; `models.py:291-324`.

**Target:** Tenant-owned `PhoneNumberAssignment` and `HandoffDestination`, normalized identity, ownership immutability, semantic inbound routing, and opaque `route_version`.

**Classification:** MODIFY.

**Gap:** The internal route returns `assignment_id`, `tenant_id`, phone number, and raw `generation` at `interfaces/http/app.py:396-422`, rather than target `InboundRoute`. Handoff material similarly exposes resource-oriented data.

**Missing evidence / uncertainty:** The target does not state whether the current additional “one enabled assignment per tenant” constraint is intended; classify that behavior TARGET-SILENT.

#### Integrations

**Repository fact:** Integration creation requires `tenant_id` in the body, only HTTP is accepted, and execution material is requested by connection UUID.

**Evidence:** `interfaces/http/app.py:117-132`, `807-834`; `application/managed_resources.py:249-302`; `execution_materialization.py:113-167`.

**Target:** Tenant-scoped `IntegrationConnection`, immutable ownership, stable semantic key, registry kind, optional credential linkage, validation, enable/disable, and execution material by semantic integration key.

**Classification:** MODIFY/MIGRATE.

**Gap:** Current routes are global `/v1/managed-resources/integration-connections`; target routes encode tenant ownership. Current runtime material includes connection ID/generation and credential version fields, which are not part of target `IntegrationExecutionMaterial`.

### F. High-level configuration application services

**Repository fact:** The only configuration application service is low-level `ComponentService`, with individual draft/publish/rollback methods. No high-level configuration service classes or configuration endpoints were found.

**Evidence:** `application/components.py:25-166`; `interfaces/http/app.py:313-321`; application service inventory from `rg` shows only `ComponentService`, `ManagedResourceService`, `ExecutionSnapshotService`, and `ExecutionMaterializationService`.

**Target:** Add semantic `SystemConfigurationService`, `PlatformConfigurationService`, and `TenantConfigurationService` with get/plan/apply/publish behavior and atomic semantic transactions.

**Classification:** ADD.

**Gap:** Current callers orchestrate individual component operations. Admin Web’s `control-plane.tsx:58-207` reads draft and active separately, saves one component at a time, and publishes one component at a time. `agentctl/application/workspace.py:69-117` similarly loops over individual resources.

**Affected code/consumers:** Control Plane application/interfaces, Admin Web, agentctl.

**Critical lifecycle differences:**

- System apply must update all changed live components atomically.
- Platform apply must immediately apply catalogs but only save prompt drafts.
- Tenant apply must immediately update live state while leaving published revisions unchanged.
- Platform/tenant publish must publish all applicable drafts atomically or none.

No current implementation provides these guarantees.

### G. Execution architecture

**Repository fact:** An immutable `ExecutionSnapshot` row exists and is created inside a repeatable-read transaction.

**Evidence:** `domain/runtime_execution_snapshot.py:57-68`; `application/runtime_materialization.py:39-92`; `models.py:356-376`.

**Target:** Resolve effective state, validate it, persist one complete immutable snapshot, derive consumer projections, and late-bind secrets/materials. The snapshot is internal and addressed externally by opaque `execution_id`.

**Classification:** KEEP/MODIFY.

**Gap:** Current snapshot persistence is the strongest compatible seam, but:

- API uses `snapshot_id` and `/execution-snapshots/*`.
- Backend reads raw `ExecutionSnapshot`.
- `ExecutionSnapshot` transport exists in `packages/contracts/src/contracts/execution_snapshot.py`.
- Snapshot payload includes runtime, agent, prompts, knowledge, capabilities, post-call, handoff, phone assignment, and provenance, which consumers parse directly.
- Consumer DTOs carry `execution_snapshot_id`.

**Affected code/consumers:** CP, Backend, Voice Agent, Worker, `packages/contracts`.

**Codex inference:** Snapshot creation itself is close to target, but projection derivation has not been made a first-class contract boundary.

### H. Consumer topology

#### Backend

**Repository fact:** Backend directly creates and reads snapshots, resolves phone numbers, requests integration material, and requests handoff material.

**Evidence:** `backend/platform/control_plane.py:26-104`; `backend/modules/calls/service.py:84-145`, `512-545`.

**Target:** Backend uses semantic internal operations and receives projections/materials without raw snapshot or provider graph knowledge.

**Classification:** MIGRATE.

#### Voice Agent

**Repository fact:** Voice Agent receives a Backend runtime context and directly fetches secrets from Control Plane using a service token.

**Evidence:** `voice_agent/backend.py:105-130`; `voice_agent/settings.py:15-19`; `voice_agent/main.py:482-489`.

**Target:** Context comes through Backend; direct Control Plane access is restricted to authorized late-bound secret material.

**Classification:** MODIFY/MIGRATE.

The access pattern is directionally aligned, but endpoint names and snapshot terminology are not.

#### Worker

**Repository fact:** Worker has no Control Plane client. It asks Backend for integration material and sends `execution_snapshot_id` as a query parameter.

**Evidence:** `job_worker/worker.py:995-1025`.

**Target:** Worker has no direct Control Plane dependency and receives `WorkerExecutionContext`/integration material through Backend using opaque execution identity.

**Classification:** MODIFY/MIGRATE.

The service boundary is aligned; the contract is not.

#### agentctl and Admin Web

Both consume low-level component APIs.

**Evidence:** `agentctl/control_plane.py:45-177`; `admin-web/src/core/configuration/control-plane.tsx:58-207`; `admin-web/vite.config.ts:35-47`.

**Target:** High-level semantic configuration is primary; low-level APIs are expert surfaces.

**Classification:** MIGRATE.

### I. HTTP contract

**Repository fact:** Management routes are under `/v1/scopes/*` and `/v1/managed-resources/*`. Raw execution routes also exist under `/v1/*`.

**Evidence:** `interfaces/http/app.py:226-239`, `313-351`; generated OpenAPI route inventory in `packages/admin-client/openapi/control-plane.openapi.json:875-3449`.

**Target:** Management under `/management/v1/*`; internal under `/internal/v1/*`; operations under `/health` and `/ready`; no generic `/v1/*`.

**Classification:** REPLACE.

**Gap:** Current route namespaces, scope route shapes, resource routes, execution endpoints, and raw snapshot endpoints conflict with the frozen contract. Compatibility routes are unnecessary because the product is unlaunched.

### J. DTO / transport boundary

**Repository fact:** Low-level request DTOs include schema versions, expected draft versions, expected active revision IDs, expected resource generations, and caller-supplied actor bodies.

**Evidence:** `interfaces/http/app.py:69-149`; `interfaces/http/app.py:754-777`, `823-847`.

**Target:** Semantic DTOs hide lifecycle internals from high-level callers; runtime DTOs do not expose `ComponentAddress`, revisions, provider graphs, credential graphs, or raw snapshots.

**Classification:** REPLACE/MODIFY.

**Gap:** The current runtime context includes `snapshot_runtime`, `execution_snapshot_id`, and `voice_runtime_revision_id`.

**Evidence:** `backend/runtime/execution_context.py:64-83`; `packages/contracts/src/contracts/voice.py:92`; `packages/contracts/src/contracts/execution_snapshot.py:8-13`.

Manual/duplicate transport definitions also exist in consumers, particularly Backend’s reconstruction logic and Admin Web’s local `ComponentSnapshot` type at `admin-web/src/core/configuration/control-plane.tsx:46-50`.

### K. Concurrency

**Repository fact:** Current APIs use numeric expected versions in bodies/query parameters. Admin Web creates quoted ETags but parses them back to integers.

**Evidence:** `interfaces/http/app.py:69-78`, `105-115`, `127-149`; `admin-web/src/core/configuration/control-plane.tsx:52-56`, `94-105`; `agentctl/control_plane.py:85-137`.

**Target:** Opaque ETag on reads, `If-Match` on mutations, stale token → `412`.

**Classification:** REPLACE/MODIFY.

**Gap:** Current `If-Match` is an adapter around exposed numeric lifecycle fields. The target requires the token to be opaque and semantic configuration/resource-specific.

### L. Idempotency

**Repository fact:** No Control Plane `Idempotency-Key` handling or replay persistence was found. Backend call creation has separate idempotency fields and lookup logic.

**Evidence:** Control Plane HTTP/application/persistence search found no idempotency implementation; Backend `modules/calls/service.py:331-389` contains `admin_idempotency_key` handling.

**Target:** Idempotency lookup precedes concurrency validation; mutation and replay record commit atomically. Required for configuration apply/publish, managed-resource mutations, credential rotation/revocation, enable/disable commands, and execution creation.

**Classification:** ADD.

**Gap:** Control Plane retries can currently repeat mutations or duplicate execution creation unless protected elsewhere.

**Missing evidence / uncertainty:** Exact replay retention is target-silent; `CONTRACTS.md:1789-1804` explicitly leaves it unresolved.

### M. Transaction boundaries

**Repository fact:** Application services generally delegate directly to repositories. Repository classes own session/transaction helpers.

**Evidence:** `application/components.py:32-79`; `application/managed_resources.py:185-302`; repository transaction helper identified at `infrastructure/persistence/repository.py:64-71`; managed-resource transaction helper at `infrastructure/persistence/managed_resources.py:64-71`.

**Target:** Application services own one semantic transaction per use case; no transaction remains open across external validation.

**Classification:** MODIFY.

**Gap:** Existing individual commands may be atomic, but no application-level transaction covers complete platform/tenant configuration apply or publish. HTTP validation is also partially orchestrated in handlers, for example integration validation at `interfaces/http/app.py:873-898`.

### N. Authorization and error model

**Repository fact:** Separate management and internal authentication implementations exist. Management uses one configured bearer token; internal uses service-specific JWT secrets/scopes.

**Evidence:** `interfaces/http/service_auth.py:14-23`, `46-113`; `interfaces/http/app.py:226-239`.

**Target:** Separate management principal and service principal boundaries, precise internal scopes, no Backend management privileges, Worker without CP credentials, authenticated principal as audit actor.

**Classification:** MODIFY.

**Gap:** Management enforcement is attached to generic `/v1/*` middleware rather than `/management/v1/*`. Current route set exposes resource operations without a target-shaped scope taxonomy.

Current errors are ad hoc `detail` objects.

**Evidence:** `interfaces/http/app.py:241-287`.

Target requires shared `ErrorResponse` and `ValidationIssue`, including distinct 409, 412, and 422 semantics.

**Classification:** REPLACE/MODIFY.

### O. OpenAPI and shared contracts

**Repository fact:** Control Plane OpenAPI snapshots and Admin Web generated clients exist. The generated schema contains legacy `/v1/*` paths and expected numeric concurrency fields.

**Evidence:** `scripts/export_control_plane_openapi.py:11-74`; `packages/admin-client/openapi/control-plane.openapi.json:55-62`, `486-591`, `875-3449`; `admin-web/orval.config.ts:14-23`.

**Target:** OpenAPI is the machine-readable source of truth; consumers use generated/shared transport contracts; Control Plane domain/persistence objects are not exported.

**Classification:** MODIFY.

**Gap:** Generation is present, but the source contract is the wrong contract. Backend and runtime code also manually reconstructs and duplicates transport shapes.

### P. Tests

**Repository fact:** Tests cover current versioned components, runtime resolution, managed resources, authentication, NATS/outbox, snapshot materialization, Admin Web component editing, and agentctl workspace semantics.

**Evidence:**

- `apps/control-plane-service/tests/unit/test_components.py`
- `apps/control-plane-service/tests/unit/test_runtime_components.py`
- `apps/control-plane-service/tests/unit/test_runtime_resolver.py`
- `apps/control-plane-service/tests/integration/test_runtime_resolution.py`
- `apps/control-plane-service/tests/integration/test_managed_resources.py`
- `apps/control-plane-service/tests/unit/test_service_auth.py`
- `apps/control-plane-service/tests/integration/test_outbox.py`
- `apps/agentctl/tests/test_workspace_core.py`
- `apps/agentctl/tests/test_did.py`
- `apps/admin-web/tests/control-plane-client.test.ts`
- `apps/admin-web/tests/authoring-state.test.ts`

**Target:** Tests must protect target lifecycle, atomic configuration operations, reference/ownership validation, ETag/If-Match, idempotency, immutable execution, secret isolation, and projection boundaries.

**Classification:** MODIFY/REPLACE/ADD.

**Gap:** Existing tests are useful for low-level versioned lifecycle and managed-resource mechanics, but many encode legacy routes, numeric versions, per-component orchestration, raw snapshot contracts, and non-atomic publish behavior.

## 5. Legacy concepts with no target role

- `ComponentSnapshot` as a public/runtime concept  
  Current role: combines address, draft, active revision, and state.  
  Target responsibility: low-level `VersionedComponent` DTO only; high-level APIs expose semantic configuration status.  
  Classification: REPLACE as a transport concept.

- Generic `ComponentService` as the primary configuration workflow  
  Current role: clients save, publish, discard, and rollback individual components.  
  Target responsibility: remain only as low-level expert management behind application services.  
  Classification: MODIFY, while replacing its use as the normal workflow.

- Runtime components stored as versioned components  
  Current role: stores defaults/policies through draft/revision lifecycle.  
  Target responsibility: system and tenant live components.  
  Classification: REPLACE.

- `ExecutionSnapshot` as consumer transport  
  Current role: Backend and contracts deserialize and inspect it.  
  Target responsibility: internal persistence artifact only.  
  Classification: REPLACE as transport, KEEP as persistence concept.

- `snapshot_id` / `execution_snapshot_id`  
  Current role: persistence-oriented identifier in APIs, database models, jobs, and runtime contexts.  
  Target responsibility: opaque `execution_id`.  
  Classification: MIGRATE.

- `/v1/scopes/*` and `/v1/managed-resources/*`  
  Current role: all management APIs.  
  Target responsibility: `/management/v1/*` with semantic scope-specific routes.  
  Classification: DELETE/REPLACE.

- `expected_draft_version` and `expected_generation` as HTTP contract fields  
  Current role: caller-visible concurrency controls.  
  Target responsibility: opaque ETag/If-Match.  
  Classification: REPLACE.

- `agent.tenant`, `knowledge.tenant`, `capabilities.tenant`, and `post_call.tenant` as independently registered generic components  
  Current role: runtime agent, knowledge, capability, and post-call data are separate low-level components.  
  Target responsibility: target tenant semantic components, with Actions represented as an aggregate of `ActionsDefinition` and `ActionsAvailability`.  
  Classification: MIGRATE/REPLACE.

  **Target-silent:** The frozen documents do not specify the exact mapping of current capability and post-call schemas into `ActionsDefinition`, runtime actions, or worker projections. Do not invent that mapping.

- HTTP-only integration restriction  
  Current role: database and application logic reject other integration kinds.  
  Target responsibility: registry-driven integration kinds.  
  Classification: REPLACE.

## 6. Missing target capabilities

### Domain

- `LiveComponent` domain primitive and repository.
- `Catalog` domain model and persistence.
- Explicit `ArchitectureRegistry`.
- Explicit `ComponentDefinitionRegistry` API surface.
- `DeploymentKindRegistry`.
- `IntegrationKindRegistry`.
- Scoped credentials.
- Target semantic tenant/platform/system aggregates.
- Explicit target ownership/reference validation rules.

### Application

- `SystemConfigurationService`.
- `PlatformConfigurationService`.
- `TenantConfigurationService`.
- Atomic mixed-lifecycle apply.
- Atomic multi-component publish.
- Semantic diff and plan results.
- Complete cross-object configuration validation.
- Target-shaped `CredentialService`, `ProviderService`, `TelephonyService`, and `IntegrationService` boundaries.

### Contract

- `/management/v1/*` API.
- High-level configuration endpoints.
- Target low-level scope-specific component endpoints.
- Target catalog endpoints.
- Target registry discovery endpoints.
- Target internal `/executions/*` endpoints.
- `BackendExecutionContext`.
- `VoiceExecutionContext`.
- `WorkerExecutionContext`.
- Target `RuntimeSecretMaterial`.
- Target `IntegrationExecutionMaterial`.
- Target `HandoffExecutionMaterial`.
- Target `InboundRoute`.
- Shared `ErrorResponse`.
- Shared `ValidationIssue`.
- Opaque ETag semantics with 412 responses.
- Idempotency-Key replay contract.

### Execution

- Projection derivation from one snapshot as a first-class service/API boundary.
- Opaque `execution_id`.
- Protection against raw snapshot transport.
- Consumer-specific projection filtering.
- Consistent late-bound material tied to execution tenant/context.
- Worker context/action projection.

### Infrastructure

- Idempotency replay persistence.
- Transaction boundaries around semantic application services.
- Schema for live components.
- Schema for catalogs.
- Scope/ownership persistence for credentials.
- Registry-driven resource validation.
- Target OpenAPI snapshots and generated clients.
- Coordinated management/internal authentication scopes.

## 7. Consumer impact map

| Consumer | Current Control Plane dependency | Legacy concepts used | Required target dependency | Expected breaking changes |
|---|---|---|---|---|
| Backend | `ControlPlaneClient` creates/reads snapshots, resolves phone, fetches integration/handoff material | `ExecutionSnapshot`, `snapshot_id`, raw provider/resource payloads | Semantic internal execution creation, voice/worker projections, inbound route, late-bound materials | Replace raw snapshot parsing; rename IDs; stop reconstructing projections |
| Voice Agent | Backend runtime context plus direct CP secret call | `execution_snapshot_id`, snapshot secret path | Voice context through Backend; direct CP only for runtime secret material | New secret endpoint and opaque execution ID; remove snapshot terminology |
| Worker | Backend integration-material API; no direct CP | `execution_snapshot_id`, integration connection material with raw IDs/generations | Worker context and integration material through Backend | Job and Backend contracts change; retain no direct CP dependency |
| agentctl | Direct low-level CP client and workspace orchestration | scopes, drafts, expected versions, per-component publish | High-level configuration APIs; low-level expert APIs only where needed | Rewrite workspace plan/push/publish semantics and concurrency |
| Admin Web | Generated low-level CP client through `/control-plane` proxy | draft/revision APIs, raw component snapshots, numeric ETags | Generated high-level management client and target low-level client | Rewrite configuration UI data flow; proxy namespace changes |

## 8. Persistence/schema impact

Current Control Plane schema contains:

- `configuration_components`
- `configuration_component_drafts`
- `configuration_component_revisions`
- `credentials`
- `credential_versions`
- `provider_connections`
- `model_deployments`
- `integration_connections`
- `handoff_destinations`
- `phone_number_assignments`
- `execution_snapshots`
- `outbox_messages`

**Evidence:** `infrastructure/persistence/models.py:29-417`; migration `0001_initial_control_plane.py:20-310`.

Recommended classification for future schema work:

| Current schema | Target treatment |
|---|---|
| Configuration component/revision/draft tables | Reuse/modify for `VersionedComponent`; remove client-owned schema-version semantics |
| New live-component table or equivalent | ADD |
| Credentials | Modify to include immutable scope/ownership semantics |
| Credential versions | Reuse substantially |
| Provider connections | Modify for registry/scope/reference rules |
| Model deployments | Modify for registry validation and target DTOs |
| Integration connections | Modify for registry-driven kinds and tenant ownership contract |
| Handoff destinations | Reuse/modify |
| Phone assignments | Reuse/modify; review extra tenant uniqueness constraint |
| Execution snapshots | Reuse as internal immutable artifact; rename external terminology only |
| Outbox | Target-silent; preserve only if future event decisions require it |
| Catalog tables | ADD |
| Idempotency replay table | ADD |
| Registry persistence | Normally not required; registries are code-owned |

Because databases are empty, schema replacement or destructive restructuring is acceptable. No persistent-data migration design is required. Consumer/code migration remains necessary.

## 9. Test impact map

### Worth preserving substantially

- Versioned draft/publish/rollback domain tests.
- Component schema and allowed-scope validation tests.
- Credential encryption, rotation, and revocation tests.
- Provider/deployment reference validation tests.
- Phone normalization and uniqueness tests.
- Handoff/integration ownership validation tests.
- Repeatable-read snapshot persistence tests.
- Secret material late-binding tests.
- Separate service-authentication tests.
- Outbox tests, if the event decision remains in scope.

### Require semantic rewrite

- `apps/control-plane-service/tests/integration/test_components.py`
  - Replace legacy route and numeric concurrency assumptions.
- `apps/control-plane-service/tests/integration/test_runtime_components.py`
  - Split versioned and live lifecycle tests.
- `apps/control-plane-service/tests/integration/test_runtime_resolution.py`
  - Assert snapshot immutability and projection origin.
- `apps/control-plane-service/tests/integration/test_managed_resources.py`
  - Replace `/v1/managed-resources/*`, body generations, and caller actor fields.
- `apps/agentctl/tests/test_workspace_core.py`
  - Replace per-component orchestration with high-level configuration semantics.
- `apps/agentctl/tests/test_did.py`
  - Replace legacy resource paths and generation bodies.
- `apps/admin-web/tests/control-plane-client.test.ts`
  - Replace `/control-plane` → `/v1` assumptions.
- `apps/admin-web/tests/authoring-state.test.ts`
  - Replace draft/version-centric normal workflows.

### Legacy architecture tests to remove or replace

- Tests asserting raw `ExecutionSnapshot` is returned to Backend.
- Tests asserting `execution_snapshot_id` is the runtime contract.
- Tests asserting generic `/v1/scopes/*` or `/v1/managed-resources/*` routes.
- Tests asserting clients supply `expected_draft_version` or `expected_generation`.
- Tests asserting per-component publish is sufficient for normal configuration workflows.

### Missing invariant tests

- Live components have no drafts/revisions/publish.
- System configuration apply is atomic.
- Tenant mixed live/draft apply is atomic.
- Platform catalog apply plus prompt draft save is atomic.
- Platform/tenant publish is all-or-nothing.
- Catalog edits do not rewrite prompt history.
- ETag/If-Match stale state returns 412.
- Idempotency replay precedes concurrency validation.
- Mutation and idempotency record commit atomically.
- Lost-response execution retry does not create duplicate executions.
- Snapshot contains no secret values.
- Existing snapshot is not re-resolved.
- All consumer contexts derive from the same snapshot.
- Runtime contexts exclude component/resource lifecycle internals.
- Worker has no Control Plane dependency or credentials.
- Credential scope and cross-tenant reference rules.
- Registry-driven provider/deployment/integration validation.
- Late-bound material belongs to the execution tenant/context.
- Shared `ErrorResponse` status mapping.

## 10. Explicit uncertainties / target-silent behavior

- Exact database table names and repository interface names for target primitives.
- Exact mapping of current `agent.tenant` to `AgentPersonality`.
- Exact mapping of current `capabilities.tenant` and `post_call.tenant` to `ActionsDefinition`, runtime actions, and post-call actions.
- Exact representation of `KnowledgePrompt / RAG`.
- Exact catalog archival lifecycle; target currently specifies enable/disable and marks archival unresolved.
- Exact management token issuer/format.
- Exact idempotency replay retention.
- Exact `CreateExecutionRequest.context` schema.
- Exact typed capability unions for deployment kinds.
- Exact semantic-key normalization beyond domain constraints.
- Whether existing outbox event taxonomy remains part of the target implementation.
- Whether the current extra uniqueness rule allowing at most one enabled assignment per tenant is intended.
- Whether current `snapshot_runtime` fields have a required target consumer; target says raw snapshot transport is forbidden.
- MISSING EVIDENCE: no repository proof that all current Control Plane databases are empty; this is supplied as project-state instruction and should be treated as an external premise for schema decisions.

## 11. Preconditions for `REFACTOR_PLAN.md`

The future plan must account for these hard relationships:

- The `LiveComponent` model, persistence, registry, and lifecycle APIs must be established before system and tenant configuration services.
- Catalog persistence and prompt scope modeling must be settled before `PlatformConfigurationService`.
- Credential scope/reference rules must precede provider, integration, and execution validation.
- Snapshot persistence can be reused independently, but consumer projection contracts must be defined before Backend/Voice Agent migration.
- OpenAPI must be regenerated together with generated Admin Web and Python client changes.
- Backend, Voice Agent, Worker, agentctl, and Admin Web contract changes are coordinated breaking changes; legacy route compatibility is unnecessary.
- Worker must remain free of direct Control Plane credentials throughout.
- Execution snapshot immutability and secret isolation tests should precede consumer projection implementation.
- Atomic high-level configuration apply/publish tests should precede implementation of those application services.
- Idempotency persistence and transaction ownership must be designed before enabling retry-sensitive mutation endpoints.
- Management and internal namespace/auth changes must be coordinated with all clients and deployment wiring.
- Outbox/NATS behavior requires an explicit target decision before it is preserved or removed.
- Empty databases permit destructive schema replacement; no persistent-data migration should constrain the design.

Self-review: the frozen documents were treated as authoritative; current behavior was reported as legacy evidence; facts, inferences, target requirements, conflicts, and missing evidence were separated; consumers outside Control Plane were inspected; no compatibility layer, migration procedure, code, test, migration, architecture-document edit, or `REFACTOR_PLAN.md` was created.
