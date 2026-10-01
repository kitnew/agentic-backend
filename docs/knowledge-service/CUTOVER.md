# Knowledge Service V1 Production Cutover

> Status: **frozen production cutover specification**
>
> This document defines the controlled transition from the production inline
> Knowledge implementation to the frozen Knowledge Service v1 target.
>
> It is a migration specification, not a permanent runtime compatibility contract.

---

## 1. General policy

The system is already in production. Existing tenant Knowledge state, published
revision history, and executions created under the current schema are production
data and must be treated accordingly.

The cutover must therefore satisfy all of the following:

- no destructive reset of valid tenant Knowledge state;
- no silent loss of active/draft/revision semantics;
- no purge of execution snapshots that may still be used by active, resumable, or
  retained production executions;
- no long-lived database transaction around Knowledge Service network calls;
- no permanent dual semantic source of truth;
- explicit observability, verification, and rollback gates for every migration phase.

The permanent target remains:

```text
Knowledge schema_version = 2
ExecutionSnapshot schema_version = 4
```

Temporary compatibility is permitted only to keep production consumers operational
while their data/executions cross that boundary. It must be bounded, documented, and
removed after the exit criteria in this document are met.

---

## 2. Target and migration-only state

### Permanent target

Control Plane tenant Knowledge:

```text
Knowledge schema_version = 2
Knowledge = {
  document_refs: UUID[]
}
```

Voice execution materialization:

```text
ExecutionSnapshot schema_version = 4
voice.knowledge.document_refs
voice tenant_id
```

The permanent target has no inline `Knowledge.content` runtime path.

### Migration-only compatibility

During the production cutover, implementations may temporarily support:

```text
reading legacy Knowledge schema_version = 1
reading legacy ExecutionSnapshot schema_version = 3
migration mappings / checkpoints
per-tenant cutover state
rollback flags required by this specification
```

Migration compatibility must not create a permanent semantic form containing both:

```text
content + document_refs
```

for one authoritative Knowledge value.

A tenant is authoritative on exactly one Knowledge schema at a time.

---

## 3. Production migration phases

The migration is executed in explicit phases. A later phase must not begin until the
previous phase has met its verification gate.

### Phase 0 — inventory, backup, and preflight

Before application behavior changes:

1. take normal production backups/snapshots for the Control Plane databases that
   contain Knowledge lifecycle state and execution snapshots;
2. inventory all tenants with Knowledge v1 state;
3. inventory Knowledge draft/active/revision records that contain inline content;
4. determine the retention/usage window for schema-3 execution snapshots;
5. verify expected document volume, source size, embedding capacity, PostgreSQL
   capacity, and MinIO capacity;
6. verify that deployment rollback can restore the previous application version
   without requiring destructive schema rollback.

A failed preflight blocks the cutover.

### Phase 1 — additive infrastructure deployment

Deploy the Knowledge Service and all infrastructure required by the target before any
tenant becomes dependent on it:

```text
Knowledge Service application
Knowledge Service PostgreSQL schema
pgvector extension
Knowledge Service Alembic head
private Knowledge Service MinIO bucket
service-specific MinIO credentials
internal authentication for resolve/search
management authentication boundary
```

The new service may be dark/unused at this phase.

Control Plane/Backend/Voice Agent releases deployed in this phase must remain able to
serve the current production schema while introducing the temporary compatibility
needed by later phases.

### Phase 2 — legacy Knowledge backfill

Legacy inline Knowledge is migrated without changing the tenant's current runtime
authority.

For every tenant, enumerate every distinct legacy inline Knowledge value that must
remain representable for:

- current draft state;
- current active/published state;
- retained immutable Knowledge revisions that can participate in rollback/history.

A non-empty legacy inline value is imported as an immutable KnowledgeDocument source.
The source bytes must preserve the legacy text faithfully. A generated Markdown
artifact is acceptable because plain text is valid Markdown.

An empty legacy Knowledge value maps to:

```text
document_refs: []
```

The backfill process must be idempotent. Re-running it for the same legacy semantic
source must converge on the previously recorded migration result rather than creating
unbounded duplicate canonical documents.

Backfill metadata must preserve enough mapping to prove:

```text
legacy tenant + legacy Knowledge state/revision
→ exact migrated Knowledge.document_refs
```

The mapping is migration metadata, not a new Knowledge Service domain concept.

Backfill must not make v2 authoritative yet.

### Phase 3 — per-tenant reconciliation and validation

Because production writes may occur while passive backfill is running, a tenant must
be reconciled immediately before its cutover.

For one tenant:

1. enter the existing Control Plane tenant command serialization/concurrency boundary;
2. reload the current Knowledge v1 draft/active/revision state;
3. identify legacy values changed since the initial backfill;
4. leave the Control Plane DB transaction before any Knowledge Service network call;
5. import/resolve the missing immutable documents;
6. enter a fresh Control Plane tenant command transaction;
7. reload current state again and validate ETag/concurrency;
8. abort and retry reconciliation if the legacy state changed again;
9. verify that every state/revision required by the cutover has a complete v2 mapping.

The implementation must not keep a Control Plane database transaction open across
Knowledge Service, MinIO, or embedding-provider network calls.

A tenant that cannot be fully reconciled is not cut over.

### Phase 4 — tenant authority switch

After reconciliation succeeds, switch that tenant from Knowledge schema v1 authority
to Knowledge schema v2 authority atomically within the Control Plane lifecycle
boundary.

The switch must preserve:

- the semantic meaning of the active/published Knowledge value;
- the semantic meaning of the current draft value;
- retained revision/rollback behavior for migrated legacy revisions;
- Control Plane ETag/concurrency semantics.

After the tenant switch:

- new Knowledge writes for that tenant use schema version 2 only;
- low-level and high-level Knowledge write paths validate `document_refs` through
  Knowledge Service;
- no new schema-v1 Knowledge state is created for that tenant.

A compatibility reader may still exist globally because other tenants may not yet be
cut over.

### Phase 5 — execution schema switch

New executions for a v2-authoritative tenant are materialized as schema version 4 and
contain:

```text
trusted tenant_id
voice.knowledge.document_refs
```

They do not contain raw tenant Knowledge text as the RAG source of truth.

Existing schema-3 executions created before the switch remain valid for their normal
production lifetime. A temporary schema-3 reader/runtime path must remain available
for as long as a schema-3 execution can legitimately be resumed, retried, inspected,
or otherwise executed by production behavior.

No new schema-3 executions may be created after the execution cutover for the tenant.

### Phase 6 — client migration

After a tenant is v2-authoritative, management/configuration clients migrate from:

```text
Admin Web inline Knowledge textarea workflow
agentctl inline knowledge.md projection
```

to:

```text
Knowledge Service document upload/list/get
Control Plane Knowledge.document_refs configuration
```

The old client path must be disabled for a tenant once it would otherwise create new
schema-v1 writes.

### Phase 7 — compatibility removal

Legacy compatibility is removed only after all removal gates in section 11 are met.

---

## 4. Control Plane Knowledge v1 → v2 preservation rules

Current legacy semantic form:

```text
Knowledge schema_version = 1
Knowledge = {
  content: string
}
```

Target semantic form:

```text
Knowledge schema_version = 2
Knowledge = {
  document_refs: UUID[]
}
```

The migration is a controlled representation conversion, not an attempt to infer or
rewrite the tenant's prose.

The importer must not summarize, normalize meaning, rewrite, or semantically edit
legacy Knowledge text. It creates an immutable document source representing the
legacy text and maps the Control Plane state/revision to that document reference.

Historical revision preservation matters because Control Plane owns immutable
Knowledge revision and rollback semantics. A legacy revision that remains addressable
for rollback/history must not silently lose its Knowledge meaning during cutover.

A one-time representation migration may rewrite the stored serialized value of a
legacy Knowledge revision from schema v1 to its semantically equivalent schema-v2
value. This is a schema/data migration, not a domain edit. It must preserve the
revision's existing identity, ordering, timestamps/audit metadata, and semantic
meaning. It must not create an apparent new tenant edit merely because the storage
representation changed.

If the Control Plane persistence model cannot safely representation-migrate retained
revisions in place, the implementation must introduce an explicit migration mapping
that preserves the same externally observable history and rollback behavior until a
safe representation migration is possible. Permanent runtime dependence on schema-v1
revision decoding is not acceptable as the final state.

A migration may intentionally reuse one migrated immutable document for multiple
legacy states/revisions that contain the exact same source content within the same
tenant. This is migration behavior only and does not redefine `content_hash` as
KnowledgeDocument identity or tenant-wide deduplication semantics.

---

## 5. ExecutionSnapshot v3 → v4

Legacy schema version 3 contains:

```text
voice.prompts.knowledge
```

Target schema version 4 contains:

```text
voice.knowledge.document_refs
```

and the Voice execution projection also includes trusted:

```text
tenant_id
```

Production rules:

1. schema-3 snapshots are not purged merely because v4 is deployed;
2. existing schema-3 snapshots remain readable for their supported execution
   lifetime;
3. new executions switch to schema 4 only after the owning tenant's Knowledge v2
   mapping is authoritative and validated;
4. after the switch, schema 4 is the only version created for that tenant;
5. schema-3 compatibility is removed only after the defined retention/usage window
   proves that no supported production consumer can still require it.

The permanent target still has no schema-3 compatibility reader.

---

## 6. Control Plane external validation and transaction ordering

Knowledge v2 introduces external validation of `document_refs`.

The required order for any operation that accepts a new Knowledge semantic value is:

```text
local schema validation / canonicalization
        ↓
Knowledge Service resolve call
        ↓
enter Control Plane tenant command transaction
        ↓
reload current state / validate ETag and concurrency
        ↓
remaining DB-backed semantic validation
        ↓
atomic write
        ↓
commit
```

Knowledge Service network calls must not occur while the Control Plane database
transaction is open.

Both:

```text
TenantConfiguration plan/apply
```

and the supported low-level:

```text
Knowledge draft write
```

must enforce the same reference-validation rule.

Publish does not re-resolve already accepted immutable document references because
v1 KnowledgeDocuments are immutable and cannot be hard-deleted.

---

## 7. Database and migration ownership

Knowledge Service owns:

```text
its PostgreSQL schema/tables
its Alembic history/version table
its pgvector-backed retrieval records
```

Control Plane continues to own its own schema and migrations.

Backend continues to own its own migrations.

Deployment must run every service-owned migration head required by the deployed
release.

At minimum deployment migration orchestration must execute:

```text
Backend migrations
Control Plane migrations
Knowledge Service migrations
```

before the corresponding release is considered ready for its migration phase.

The Knowledge Service migration path must ensure that the PostgreSQL `vector`
extension is available before vector columns are used.

Production schema migrations must be additive/compatible with the currently running
release during the compatibility window. Destructive cleanup migrations are deferred
until the compatibility-removal gates have been met and rollback no longer depends on
legacy columns/state.

---

## 8. Object storage cutover

Knowledge Service receives its own private MinIO bucket and service-specific
read/write credential.

Existing call-recording MinIO resources are not reused as semantic Knowledge storage
abstractions.

Raw Knowledge source objects are owned only by Knowledge Service.

The bucket and credentials must exist before backfill begins.

Backfill/import failures may leave orphan source objects as defined by the normal
Knowledge Service ingestion model; those objects are infrastructure artifacts and do
not make the migration semantically complete.

---

## 9. Runtime and client cutover

The permanent target removes:

```text
VoicePrompts.knowledge
[Tenant knowledge] instruction block
agentctl inline knowledge.md projection
Admin Web inline Knowledge textarea workflow
```

and replaces them with:

```text
Control Plane Knowledge.document_refs
RuntimeKnowledge.document_refs
VoiceExecutionContext.tenant_id
VoiceExecutionContext.knowledge
knowledge.search / knowledge_search
Knowledge Service document-management flow
```

Backend remains a typed pass-through for the immutable execution context.

During production migration, the old runtime/client paths may remain available only
for tenants/executions that are still explicitly on the legacy side of the cutover.
They must not be used as an implicit fallback for a v2/v4 execution.

---

## 10. Rollback policy

Rollback is defined per migration phase.

### Before tenant authority switch

Rollback is straightforward: legacy Knowledge v1 remains authoritative. Backfilled
KnowledgeDocuments and migration metadata may remain unused and can be cleaned later.

### After tenant authority switch, before new v2-native edits

The pre-cutover v1 state and migration mapping must remain retained during the
rollback window. A tenant may be switched back only through an explicit rollback
operation that restores the previously authoritative v1 state and prevents concurrent
v2 writes.

### After v2-native Knowledge changes

Automatic reverse conversion from arbitrary v2 document references back into one
legacy inline string is not part of the architecture.

Once a tenant has accepted v2-native Knowledge changes, rollback of application code
must use a release that understands v2. Restoring v1 semantics from backup is an
incident-recovery operation, not a normal feature-flag rollback.

### Execution rollback

Existing schema-3 executions continue through the temporary compatibility path.
Schema-4 executions are not converted back into schema 3.

Rollback must never broaden an execution's tenant/document scope or silently replace
its pinned Knowledge with the tenant's latest state.

---

## 11. Compatibility-removal gates

Legacy Knowledge/schema compatibility may be removed only when all of the following
are true:

- every production tenant is Knowledge schema v2 authoritative;
- no supported write path can create Knowledge schema v1 state;
- all required legacy draft/active/revision states have verified v2 mappings;
- rollback/history behavior for retained Knowledge revisions has been verified;
- all new executions are schema version 4;
- no active/resumable/retriable production execution requires schema version 3;
- the documented schema-3 retention/usage window has elapsed;
- Admin Web and agentctl no longer depend on inline Knowledge writes;
- operational dashboards show no legacy-path traffic for the agreed observation
  window;
- production backups have completed after stable v2/v4 operation;
- rollback no longer depends on legacy database columns or legacy application code.

Only after these gates pass may cleanup remove:

```text
Knowledge schema-v1 writers/readers
schema-3 execution compatibility readers
legacy inline runtime prompt materialization
legacy client write paths
temporary migration mappings/checkpoints no longer needed for audit/recovery
legacy DB columns/tables that have no remaining retention obligation
```

Cleanup itself must be deployed as a separate, reviewable migration step.

---

## 12. Observability and acceptance criteria

The production cutover must expose enough telemetry to answer, per tenant and
system-wide:

```text
backfill attempted / succeeded / failed
legacy states/revisions discovered
legacy states/revisions mapped
v1-authoritative tenants remaining
v2-authoritative tenants
schema-3 executions still observed
schema-4 executions created
resolve failures
retrieval failures
legacy runtime-path usage
```

The cutover is complete when:

- Knowledge schema version 2 is authoritative for every production tenant;
- no production write path creates inline `Knowledge.content` state;
- migrated active/draft/revision semantics have been verified;
- execution snapshot schema version 4 is authoritative for all newly created
  executions;
- supported legacy schema-3 executions have naturally drained past their retention
  window;
- Voice execution context contains trusted `tenant_id` and `document_refs`;
- raw Knowledge text is absent from schema-4 static model instructions;
- Control Plane external reference validation occurs before its DB transaction, with
  ETag/current-state validation inside the transaction;
- Knowledge Service migrations and pgvector are deployed;
- all required service migration heads run through deployment tooling;
- Knowledge Service has isolated MinIO credentials/storage;
- Admin Web/browser clients do not hold globally trusted Knowledge Service service
  credentials;
- no permanent legacy compatibility path remains;
- production backups exist for the stable post-cutover state.
