# Knowledge Service Schemas

> Status: **frozen target schemas — Knowledge Service v1**
>
> This document defines the canonical semantic schemas shared by the Knowledge
> Service, its management/internal contracts, and the Control Plane integration
> boundary.
>
> It complements:
>
> - [`ARCHITECTURE.md`](./ARCHITECTURE.md) — ownership, domain model, ingestion,
>   retrieval, and service boundaries.
> - [`CONTRACTS.md`](./CONTRACTS.md) — HTTP/API surfaces, DTO usage, authorization,
>   idempotency, errors, and transactional guarantees.
> - [`INVARIANTS.md`](./INVARIANTS.md) — non-negotiable architectural and domain
>   rules.
>
> These are **semantic and transport-facing schemas**, not PostgreSQL or MinIO
> persistence schemas. Retrieval implementation details must not reshape these
> contracts.

---

## Table of Contents

- [1. Schema conventions](#1-schema-conventions)
- [2. Common semantic types](#2-common-semantic-types)
- [3. KnowledgeDocument](#3-knowledgedocument)
- [4. Control Plane Knowledge schema v2](#4-control-plane-knowledge-schema-v2)
- [5. Document management DTO schemas](#5-document-management-dto-schemas)
- [6. Document-resolution schemas](#6-document-resolution-schemas)
- [7. Retrieval schemas](#7-retrieval-schemas)
- [8. Voice runtime knowledge projection](#8-voice-runtime-knowledge-projection)
- [9. Model-facing tool schema](#9-model-facing-tool-schema)
- [10. Cross-schema semantic rules](#10-cross-schema-semantic-rules)
- [11. Explicitly non-contractual data](#11-explicitly-non-contractual-data)

---

# 1. Schema conventions

Unless otherwise stated:

```yaml
type: object
additionalProperties: false
```

Unknown fields are rejected.

## Optionality

A field not listed in `required` is optional.

- omitted field = not provided / not applicable;
- `null` is valid only where explicitly declared;
- omission is preferred when `null` adds no distinct semantic meaning.

## Identifiers

Resource identities are opaque UUIDs.

Clients must not derive:

- tenant identity;
- storage location;
- revision identity;
- chunk identity;
- retrieval behavior

from UUID values.

## Timestamps

Timestamps use RFC 3339 / ISO 8601 UTC strings.

## Collections

Unless explicitly stated otherwise, array ordering is semantically significant.

`Knowledge.document_refs` is the exception: it has **set semantics**.

## Schema versioning

The Knowledge Service schemas in this document are schema version 1 unless otherwise
stated.

The Control Plane `Knowledge` component defined here is **schema version 2** because
the existing inline-content representation is replaced by RAG document references.

---

# 2. Common semantic types

```yaml
TenantId:
  type: string
  format: uuid

KnowledgeDocumentId:
  type: string
  format: uuid

KnowledgeDocumentRef:
  $ref: KnowledgeDocumentId

DocumentMediaType:
  type: string
  enum:
    - text/markdown
    - application/pdf

ContentHash:
  type: string
  pattern: "^sha256:[a-f0-9]{64}$"

Filename:
  type: string
  minLength: 1
  maxLength: 255

HeadingPath:
  type: array
  maxItems: 32
  items:
    type: string
    minLength: 1
    maxLength: 500

PageNumber:
  type: integer
  minimum: 1
  description: 1-based source PDF page number.
```

`KnowledgeDocumentRef` is semantically a reference to an immutable,
tenant-owned `KnowledgeDocument`.

### TenantId canonical representation

`TenantId` has UUID semantics at all service boundaries.

Canonical textual serialization is the standard lowercase hyphenated UUID form.

An internal service may use that canonical string as a storage/scope key, but a
free-form tenant string is not a separate valid tenant identity.

---

# 3. KnowledgeDocument

`KnowledgeDocument` is the sole semantic document entity owned by the Knowledge
Service.

```yaml
KnowledgeDocument:
  type: object
  additionalProperties: false
  required:
    - id
    - tenant_id
    - filename
    - media_type
    - size_bytes
    - content_hash
    - created_at

  properties:
    id:
      $ref: KnowledgeDocumentId

    tenant_id:
      $ref: TenantId

    filename:
      $ref: Filename

    media_type:
      $ref: DocumentMediaType

    size_bytes:
      type: integer
      minimum: 1

    content_hash:
      $ref: ContentHash

    created_at:
      type: string
      format: date-time
```

Semantic rules:

- `id` is stable and immutable;
- `tenant_id` is immutable;
- source content is immutable;
- `filename` describes the uploaded source and is immutable;
- changing source bytes creates another `KnowledgeDocument`;
- if this object exists canonically, it is retrieval-ready;
- object-storage paths, extracted text, chunks, vectors, and embedding metadata are
  not fields of this schema.
  
### Content hash semantics

`content_hash` provides content provenance and integrity information.

It is not:

- document identity;
- a tenant-wide uniqueness key;
- an implicit deduplication key.

Two separate successful create commands may therefore produce two distinct
`KnowledgeDocument` identities with identical source bytes and identical
`content_hash` values.

Idempotent replay of the same create command is the only v1 mechanism that returns
the same logical document for a retried request.

---

# 4. Control Plane Knowledge schema v2

The Control Plane remains the lifecycle owner of tenant `Knowledge`.

Version 2 replaces inline prompt content with immutable Knowledge Service document
references.

```yaml
Knowledge:
  schema_version: 2

  type: object
  additionalProperties: false
  required:
    - document_refs

  properties:
    document_refs:
      type: array
      maxItems: 100
      uniqueItems: true
      items:
        $ref: KnowledgeDocumentRef
      description: >
        Set of immutable KnowledgeDocument references included in this tenant
        Knowledge configuration.
```

## Semantics

`document_refs` has **set semantics**:

```text
[A, B, C] == [C, A, B]
```

Array ordering must not create a semantic configuration change.

Control Plane should canonicalize this set for:

- semantic diffing;
- ETag contribution;
- persistence comparison;
- plan/apply output.

The empty set is valid:

```yaml
document_refs: []
```

An empty published Knowledge component means that no tenant document is available
for runtime retrieval.

## Reference validation

Before a `Knowledge` value can be accepted as a valid draft, every reference must:

```text
exist
AND
belong to the tenant owning the Knowledge component
```

The Knowledge Service internal resolution contract is authoritative for this
cross-service validation.

## Legacy v1

Legacy schema version 1:

```yaml
Knowledge:
  content: string
```

is not part of the target RAG runtime model.

Target v2 is references-only. It must not support a dual form such as:

```text
content + document_refs
```

because that would create two competing tenant-knowledge sources.

---

# 5. Document management DTO schemas

These schemas support the Knowledge Service management surface.

## KnowledgeDocumentList

```yaml
KnowledgeDocumentList:
  type: object
  additionalProperties: false
  required:
    - documents

  properties:
    documents:
      type: array
      items:
        $ref: KnowledgeDocument
```

V1 returns the complete tenant document inventory and does not expose pagination
semantics.

## DocumentUpload

The upload request is `multipart/form-data`, not JSON.

Semantic form:

```text
file: binary
```

The request does not accept:

```text
tenant_id in body
document_id
media_type override
object key
chunking settings
embedding settings
metadata JSON
```

Tenant identity is derived from the management route and authenticated authorization
context.

`filename` and media type are derived from the uploaded file part and validated by
the service.

---

# 6. Document-resolution schemas

The internal resolution operation is used by Control Plane to validate semantic
document references.

## DocumentResolveRequest

```yaml
DocumentResolveRequest:
  type: object
  additionalProperties: false
  required:
    - document_refs

  properties:
    document_refs:
      type: array
      maxItems: 100
      uniqueItems: true
      items:
        $ref: KnowledgeDocumentRef
```

An empty array is valid.

## ResolvedKnowledgeDocument

The Control Plane does not need retrieval internals.

```yaml
ResolvedKnowledgeDocument:
  type: object
  additionalProperties: false
  required:
    - id
    - filename
    - media_type

  properties:
    id:
      $ref: KnowledgeDocumentId

    filename:
      $ref: Filename

    media_type:
      $ref: DocumentMediaType
```

## DocumentResolveResponse

```yaml
DocumentResolveResponse:
  type: object
  additionalProperties: false
  required:
    - documents

  properties:
    documents:
      type: array
      items:
        $ref: ResolvedKnowledgeDocument
```

Resolution is all-or-none.

If any requested reference:

- does not exist; or
- belongs to another tenant,

the request fails as an invalid semantic reference.

The service must not return a partial successful subset.

Response order follows request order for deterministic diagnostics; order has no
semantic meaning for Control Plane `Knowledge`.

---

# 7. Retrieval schemas

## KnowledgeSearchRequest

```yaml
KnowledgeSearchRequest:
  type: object
  additionalProperties: false
  required:
    - document_refs
    - query

  properties:
    document_refs:
      type: array
      maxItems: 100
      uniqueItems: true
      items:
        $ref: KnowledgeDocumentRef

    query:
      type: string
      minLength: 1
      maxLength: 1000
```

`query` must contain non-whitespace text.

The request deliberately does **not** contain:

```text
tenant_id
top_k
similarity_threshold
search_mode
embedding model
filters
reranking configuration
```

Tenant identity comes from the authenticated route context.

Retrieval tuning is service-owned.

## KnowledgePassageSource

```yaml
KnowledgePassageSource:
  type: object
  additionalProperties: false
  required:
    - document_id
    - filename

  properties:
    document_id:
      $ref: KnowledgeDocumentId

    filename:
      $ref: Filename

    heading_path:
      $ref: HeadingPath

    page_number:
      $ref: PageNumber
```

`heading_path` is present when meaningful structural provenance exists.

`page_number` is present for PDF content when source page provenance is available.

## KnowledgePassage

```yaml
KnowledgePassage:
  type: object
  additionalProperties: false
  required:
    - text
    - source

  properties:
    text:
      type: string
      minLength: 1

    source:
      $ref: KnowledgePassageSource
```

The runtime contract intentionally does not expose similarity score as factual
confidence.

## KnowledgeSearchResponse

```yaml
KnowledgeSearchResponse:
  type: object
  additionalProperties: false
  required:
    - matches

  properties:
    matches:
      type: array
      maxItems: 4
      items:
        $ref: KnowledgePassage
```

Matches are ordered from most relevant to least relevant according to the active
retrieval implementation.

An empty result is represented as:

```json
{
  "matches": []
}
```

There is no separate redundant `found` flag.

## Empty scope

A request with:

```json
{
  "document_refs": [],
  "query": "..."
}
```

is valid and deterministically returns:

```json
{
  "matches": []
}
```

The implementation should avoid unnecessary query embedding in this case.

---

# 8. Voice runtime knowledge projection

The Control Plane / Backend runtime projection must expose knowledge scope as data,
not prompt text.

Canonical semantic projection:

```yaml
RuntimeKnowledge:
  type: object
  additionalProperties: false
  required:
    - document_refs

  properties:
    document_refs:
      type: array
      maxItems: 100
      uniqueItems: true
      items:
        $ref: KnowledgeDocumentRef
```

Conceptually:

```text
VoiceExecutionContext
├── execution_id
├── tenant_id
├── ...
└── knowledge
    └── document_refs[]
```

`tenant_id` is required trusted runtime data.

The Voice Agent must not derive tenant identity from:

- model input;
- tool arguments;
- document references;
- room names;
- natural-language context.

`tenant_id` and `knowledge.document_refs` are both pinned by the immutable
execution context.

The runtime projection does not expose:

```text
Control Plane Knowledge revision number
Knowledge component draft metadata
raw document text
chunks
embeddings
vector backend details
```

Execution immutability is sufficient to pin the document scope for the call.

---

# 9. Model-facing tool schema

The model-facing tool is intentionally smaller than the internal retrieval API.

## `knowledge.search`

```yaml
KnowledgeSearchToolInput:
  type: object
  additionalProperties: false
  required:
    - query

  properties:
    query:
      type: string
      minLength: 1
      maxLength: 1000
```

The model must not receive fields for:

```text
tenant_id
document_refs
top_k
threshold
retrieval backend
embedding profile
```

Runtime code combines:

```text
tool query
+
execution tenant
+
execution knowledge.document_refs
```

to construct `KnowledgeSearchRequest`.

---

# 10. Cross-schema semantic rules

## Document identity

```text
same document ID
→ same tenant
→ same immutable source content
```

A mutable "latest version" document identity does not exist in v1.

## Tenant scope

For every referenced document:

```text
document.tenant_id == trusted tenant_id
```

is mandatory.

## Control Plane ownership

```text
Knowledge.document_refs
```

is configuration data owned by Control Plane lifecycle semantics.

`KnowledgeDocument` is resource data owned by Knowledge Service.

Neither service may silently absorb the other's lifecycle.

## Runtime scope

`RuntimeKnowledge.document_refs` is produced from the published Control Plane
Knowledge value materialized into the immutable execution context.

Runtime search must use that scope exactly.

## Search authority

`KnowledgeSearchResponse.matches[*].text` is tenant knowledge.

It is not an operational result merely because the transport operation is called a
tool.

## Static versus operational information

Knowledge search must not be used to establish:

```text
current availability
current reservation state
operation success
current handoff state
other mutable operational facts
```

## Empty knowledge

An empty Control Plane `Knowledge.document_refs` value is valid.

A runtime with an empty document scope has no tenant RAG knowledge available.

The Voice Agent may omit exposing `knowledge.search` when the execution document
scope is empty.

---

# 11. Explicitly non-contractual data

The following may exist internally but are deliberately excluded from semantic and
transport contracts:

```text
MinIO bucket name
MinIO object key
temporary object key
extracted full document text
normalized extraction blocks
chunk ID
chunk token count
chunk overlap
embedding vector
embedding dimensions
embedding provider request IDs
cosine distance / similarity score
pgvector operator/index configuration
HNSW/IVFFlat/TurboVec configuration
database primary-key layout
orphan cleanup metadata
```

Changing these does not require a semantic schema change unless the change alters a
document, tenant-isolation, publication, runtime-scope, or retrieval invariant.
