# Knowledge Service Invariants

> Status: **frozen target invariant set — Knowledge Service v1**
>
> This document contains the non-negotiable rules of the Knowledge Service target
> architecture.
>
> It is intentionally concise and normative. It does not define HTTP endpoint
> catalogs, persistence schemas, or implementation details that are free to evolve.
>
> The existing Control Plane remains authoritative for the `Knowledge`
> `VersionedComponent` lifecycle. The Knowledge Service must not duplicate that
> lifecycle.

---

## Table of Contents

- [1. Ownership and boundaries](#1-ownership-and-boundaries)
- [2. Tenant ownership](#2-tenant-ownership)
- [3. KnowledgeDocument](#3-knowledgedocument)
- [4. Ingestion](#4-ingestion)
- [5. Extraction and chunking](#5-extraction-and-chunking)
- [6. Embeddings](#6-embeddings)
- [7. Control Plane integration](#7-control-plane-integration)
- [8. Runtime scope](#8-runtime-scope)
- [9. Retrieval](#9-retrieval)
- [10. Knowledge authority](#10-knowledge-authority)
- [11. Provenance](#11-provenance)
- [12. Storage](#12-storage)
- [13. Failure isolation](#13-failure-isolation)
- [14. Change discipline](#14-change-discipline)

---

## 1. Ownership and boundaries

1. The Control Plane is the sole authority for tenant `Knowledge` draft, publish,
   immutable revision history, and rollback semantics.

2. The Knowledge Service must not implement a second tenant `Knowledge` draft,
   publication, revision, collection, or activation lifecycle.

3. The Knowledge Service is authoritative for immutable tenant
   `KnowledgeDocument` objects and the retrieval representation derived from those
   documents.

4. The Knowledge Service does not own prompts, agent behavior, execution snapshots,
   conversation state, capability outcomes, reservations, current availability, or
   other operational business state.

5. Chunks, extracted blocks, embeddings, vector indexes, similarity scores, token
   counts, and chunking parameters are retrieval/persistence artifacts rather than
   semantic domain entities.

6. Retrieval technology choices must not leak into Control Plane semantic schemas or
   model-facing tool contracts.

---

## 2. Tenant ownership

1. Every `KnowledgeDocument` belongs to exactly one tenant.

2. `KnowledgeDocument.tenant_id` is immutable.

3. A Control Plane tenant may reference only documents owned by that same tenant.

4. Cross-tenant document references are invalid.

5. Cross-tenant retrieval is forbidden regardless of vector similarity.

6. Runtime tenant identity comes from a trusted service/runtime context, never from
   model-supplied tool arguments.
   
7. The canonical cross-service tenant identity has UUID semantics.

8. An internal canonical UUID string representation does not create a separate
   tenant identity type.

9. Knowledge Service v1 management principals are globally trusted platform
   operators; per-operator tenant grants are outside the v1 authorization model.

10. Global management trust does not weaken tenant isolation for document
    addressing, Control Plane reference validation, runtime execution scope, or
    Voice Agent retrieval.

---

## 3. KnowledgeDocument

1. `KnowledgeDocument` identifies one immutable source artifact.

2. Source bytes of an existing `KnowledgeDocument` never change.

3. Replacing or editing source content creates a new `KnowledgeDocument` with a new
   identity.

4. A canonical `KnowledgeDocument` exists only when all retrieval artifacts required
   by v1 ingestion have been persisted successfully.

5. An existing canonical `KnowledgeDocument` is retrieval-ready.

6. V1 exposes no semantic update operation for `KnowledgeDocument`.

7. V1 exposes no hard-delete operation for `KnowledgeDocument`.

8. Historical Control Plane revisions must remain able to reference and retrieve the
   exact immutable documents they originally published.
   
9. `content_hash` is provenance/integrity metadata and is not
   `KnowledgeDocument` identity.

10. Identical source bytes may exist under multiple distinct
    `KnowledgeDocument` identities when they were created by distinct commands.

11. Idempotent replay of one logical create command must resolve to one canonical
    `KnowledgeDocument`.

---

## 4. Ingestion

1. V1 document ingestion is synchronous from the management API perspective.

2. A successful create response is returned only after:
   - source storage succeeds;
   - extraction succeeds;
   - normalization/chunking succeeds;
   - document embeddings succeed;
   - document metadata and retrieval records commit successfully.

3. Failed ingestion must not create a canonical usable `KnowledgeDocument`.

4. Partially produced chunks or embeddings must never become visible to runtime
   retrieval as a valid document.

5. Database transactions must not remain open across external object-storage or
   embedding-provider network calls.

6. A raw object left behind after failed ingestion is an orphan infrastructure
   artifact and does not represent a semantic document.

7. Retrying a failed upload may create a fresh ingestion attempt; retry mechanics do
   not create mutable document state.

---

## 5. Extraction and chunking

1. V1 accepts only Markdown and PDF source documents.

2. V1 PDF support requires usable extractable text already present in the PDF.

3. V1 does not perform OCR.

4. A PDF without sufficient usable extractable text is rejected rather than silently
   indexed as empty or low-quality knowledge.

5. Supported source formats are normalized into a common internal extracted-document
   representation before chunking.

6. Chunking is deterministic and implementation-owned in v1.

7. Chunking policy is not tenant-configurable in v1.

8. Structural context such as heading hierarchy should be preserved where available
   and may be included in embedding input.

9. Source provenance such as PDF page number or Markdown heading path must be
   preserved where the source format allows it.

---

## 6. Embeddings

1. V1 uses one service-wide embedding profile.

2. Tenant configuration does not select an embedding model in v1.

3. Document chunks participating in one retrieval operation must be compatible with
   the query embedding representation used for that operation.

4. An embedding-model or representation change must not reinterpret existing stored
   vectors as though they were generated by the new representation.

5. Document embedding is performed during ingestion, not in the runtime retrieval
   hot path.

6. Query embedding is performed at retrieval time.

---

## 7. Control Plane integration

1. Tenant `Knowledge` remains a Control Plane `VersionedComponent`.

2. RAG-backed `Knowledge` references immutable `KnowledgeDocument` identities rather
   than transferring full document text into runtime prompt materialization.

3. Control Plane validation of `Knowledge` document references must verify:
   - document existence;
   - same-tenant ownership.

4. Successfully validated document identity and tenant ownership remain stable
   because v1 documents are immutable and not hard-deleted.

5. Editing a Control Plane `Knowledge` draft does not change runtime retrieval scope.

6. Only Control Plane publication changes the document scope used by newly created
   executions.

7. A published Control Plane `Knowledge` revision retains its exact document
   references immutably.

8. Rolling back Control Plane `Knowledge` restores the historical document references
   represented by that revision.

9. The Knowledge Service does not require Control Plane revision IDs to model or
   retrieve a document.

---

## 8. Runtime scope

1. Runtime retrieval always targets an explicit execution-scoped document set.

2. Runtime retrieval must not implicitly resolve or search the tenant's latest
   Control Plane `Knowledge` state.

3. An execution's authorized knowledge document scope remains unchanged for the
   lifetime of that execution.

4. Publishing newer tenant `Knowledge` affects subsequently created executions, not
   already-created execution contexts.

5. The model-facing `knowledge.search` tool accepts the semantic query only.

6. Tenant identity and allowed document references are supplied by trusted runtime
   code, not by the model.

7. The model cannot expand, replace, or bypass the runtime-authorized document scope.

8. The semantic tool identity is `knowledge.search`; provider-specific function-name
   normalization does not change its semantic identity.

9. Provider-visible tool naming must never turn Knowledge retrieval into a tenant
   `ActionDefinition`.

---

## 9. Retrieval

1. V1 retrieval uses PostgreSQL + pgvector exact vector search.

2. Approximate nearest-neighbor indexing is not required for v1 correctness.

3. Tenant and allowed-document constraints are authorization/scope constraints and
   must be applied before a result can be eligible for ranking.

4. Retrieval may return only chunks belonging to:
   - the trusted tenant;
   - documents in the trusted execution scope.

5. V1 uses a small service-controlled top-k.

6. The model cannot select top-k, retrieval backend, tenant filters, document
   filters, or vector-index behavior.

7. Search must support returning no relevant matches.

8. Vector-nearest does not automatically mean relevant.

9. A relevance threshold, when enabled, must be calibrated from retrieval evaluation
   rather than treated as a universal semantic constant.

10. Similarity distance or score is retrieval metadata, not factual-confidence
    probability.

---

## 10. Knowledge authority

1. `knowledge.search` returns static tenant knowledge.

2. A passage returned through `knowledge.search` retains tenant-knowledge authority;
   it does not become higher-authority operational state merely because it was
   returned by a tool.

3. Retrieved knowledge must not override current runtime/tool results or validated
   structured context with higher authority.

4. Knowledge retrieval must never be used as proof of:
   - current availability;
   - reservation existence;
   - reservation state;
   - operation success;
   - handoff completion;
   - other current mutable business state.

5. Operational facts must come from the capability/runtime source responsible for
   those facts.

---

## 11. Provenance

1. Every returned passage must preserve enough provenance to identify its source
   document.

2. Page provenance should be returned for PDF passages when available.

3. Heading/section provenance should be returned when available.

4. Provenance is diagnostic and grounding metadata; it does not change authority
   ordering.

5. Retrieval telemetry may record internal similarity data without exposing it as
   factual certainty.

---

## 12. Storage

1. MinIO stores immutable raw source bytes.

2. Knowledge Service controls authoritative object keys; callers do not choose
   canonical MinIO paths.

3. PostgreSQL stores canonical `KnowledgeDocument` metadata and the retrieval records
   required by the active v1 implementation.

4. pgvector is the initial vector-search implementation.

5. Any future approximate/vector-specific index is derived infrastructure state.

6. A derived vector index must be rebuildable without changing
   `KnowledgeDocument` semantic identity.

7. Replacing pgvector search with another retrieval backend must not require changing
   Control Plane `Knowledge` semantics or the model-facing `knowledge.search`
   contract.

---

## 13. Failure isolation

1. Failed ingestion must not affect previously existing documents.

2. Failed Control Plane document-reference validation must not partially accept a
   tenant `Knowledge` value.

3. Retrieval failure must not expand search to another tenant or document set.

4. Retrieval failure must not authorize the agent to infer operational state from
   static knowledge.

5. External dependency failures must be surfaced as explicit service errors rather
   than silently producing incomplete or fabricated passages.

---

## 14. Change discipline

1. Do not add document lifecycle states unless asynchronous ingestion or another
   concrete requirement actually requires them.

2. Do not add knowledge collections, folders, multiple knowledge bases, or per-domain
   knowledge routing without a demonstrated product requirement.

3. Do not add OCR until image/scanned document ingestion is required.

4. Do not add BM25, hybrid retrieval, reranking, query rewriting, multi-query
   retrieval, or speculative retrieval until evaluation demonstrates a retrieval
   problem that the added mechanism addresses.

5. Do not add approximate vector indexing until scale or measured latency requires it.

6. Do not make chunking, embedding, vector-search, or retrieval-internal settings
   tenant semantic configuration without an explicit architectural revision.

7. A change that alters domain ownership, Control Plane lifecycle ownership, tenant
   isolation, runtime scope, or document immutability requires an explicit update to
   this architecture and invariant set.
