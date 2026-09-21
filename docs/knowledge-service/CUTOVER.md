# Knowledge Service V1 Cutover

> Status: **frozen one-time cutover specification**
>
> This document defines the intentional transition from the current inline
> Knowledge implementation to the frozen Knowledge Service v1 target.
>
> It is not a permanent runtime compatibility contract.

---

## 1. General policy

The project is not in production and backward compatibility with legacy Knowledge
runtime state is not required.

The implementation should therefore converge directly on the frozen target without:

- permanent compatibility adapters;
- dual Knowledge schemas;
- multi-version Knowledge decoding;
- dual-write behavior;
- schema-3 execution compatibility readers.

---

## 2. Control Plane Knowledge v1 → v2

Current:

```text
Knowledge schema_version = 1
Knowledge = {
  content: string
}
````

Target:

```text
Knowledge schema_version = 2
Knowledge = {
  document_refs: UUID[]
}
```

There is no automatic semantic conversion from arbitrary inline Knowledge text to
immutable KnowledgeDocument references.

During cutover:

1. existing Knowledge v1 draft/active/revision state may be destructively reset;
2. the ComponentDefinitionRegistry switches Knowledge to schema version 2;
3. tenant Knowledge is re-established as either:

```text
document_refs: []
```

or explicit operator-uploaded KnowledgeDocument references.

No permanent schema-v1 decoder is introduced.

No dual:

```text
content + document_refs
```

schema is permitted.

---

## 3. ExecutionSnapshot v3 → v4

Current execution snapshot schema version:

```text
3
```

contains:

```text
voice.prompts.knowledge
```

Target execution snapshot schema version:

```text
4
```

contains:

```text
voice.knowledge.document_refs
```

and the Voice execution projection also includes trusted:

```text
tenant_id
```

Existing schema-3 execution snapshots do not need to remain usable after the
cutover.

They may be purged/reset before schema version 4 becomes authoritative.

No permanent schema-3 compatibility reader is required.

---

## 4. Control Plane external validation cutover

Knowledge v2 introduces external validation of `document_refs`.

The required orchestration is:

```text
local schema validation / canonicalization
        ↓
Knowledge Service resolve call
        ↓
enter Control Plane tenant command transaction
        ↓
reload current state / validate ETag
        ↓
remaining DB-backed semantic validation
        ↓
atomic write
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

must enforce the same reference validation rule.

Publish does not re-resolve already accepted immutable document references.

---

## 5. Database and migration ownership

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

The current Backend-only migration orchestration is not sufficient for the target.

At minimum deployment migration orchestration must execute:

```text
Backend migrations
Control Plane migrations
Knowledge Service migrations
```

before the corresponding services are considered ready.

The Knowledge Service database migration path must also ensure that the PostgreSQL
`vector` extension is available before vector columns are used.

---

## 6. Object storage cutover

Knowledge Service receives its own private MinIO bucket and service-specific
read/write credential.

Existing call-recording MinIO resources are not reused as semantic Knowledge
storage abstractions.

Raw Knowledge source objects are owned only by Knowledge Service.

---

## 7. Client/runtime cutover

The target cutover removes:

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

---

## 8. Compatibility rule

If implementation becomes simpler by preserving legacy Knowledge behavior, that
alone is not a valid reason to add a compatibility layer.

A compatibility mechanism may be introduced only if a concrete current consumer
must remain operational during a defined migration slice.

Any such mechanism must be temporary, explicitly documented, and removed when the
consumer migration completes.

---

## 9. Cutover acceptance criteria

The cutover is complete when:

* Knowledge schema version 2 is authoritative;
* no inline `Knowledge.content` target path remains;
* old Knowledge v1 state cannot affect runtime behavior;
* execution snapshot schema version 4 is authoritative;
* Voice execution context contains trusted `tenant_id` and `document_refs`;
* raw Knowledge text is absent from static model instructions;
* Control Plane validation occurs before its DB transaction;
* Knowledge Service migrations and pgvector are deployed;
* all required service migration heads run through deployment tooling;
* Knowledge Service has isolated MinIO credentials/storage;
* no permanent legacy compatibility path remains.
