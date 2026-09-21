# Knowledge Service Architecture

This directory contains the frozen target specification for the Knowledge/RAG
subsystem.

## Source of truth

Read in this order:

1. [ARCHITECTURE.md](./ARCHITECTURE.md)
   - service boundaries
   - ownership
   - domain model
   - ingestion architecture
   - retrieval architecture
   - Control Plane and Voice Agent integration

2. [SCHEMAS.md](./SCHEMAS.md)
   - canonical semantic schemas
   - KnowledgeDocument
   - Control Plane Knowledge schema v2
   - runtime knowledge projection
   - retrieval schemas
   - model-facing tool schema

3. [CONTRACTS.md](./CONTRACTS.md)
   - management and internal APIs
   - DTO usage
   - authorization
   - idempotency
   - errors
   - transactional guarantees
   - Control Plane and Voice Agent contracts

4. [INVARIANTS.md](./INVARIANTS.md)
   - non-negotiable architectural, security, lifecycle, and retrieval rules

5. [CUTOVER.md](./CUTOVER.md)
   - one-time migration from the current inline Knowledge implementation
   - execution snapshot schema cutover
   - deployment migration requirements

## Status

The documents in this directory are the frozen target specification for
Knowledge Service v1.

The existing implementation is evidence of current behavior and migration
constraints. It is not authoritative when it conflicts with this specification.

Implementation must converge directly on this target unless this specification is
explicitly revised first.

## Change discipline

A change requires an explicit architecture decision before implementation if it
changes any of the following:

- domain ownership;
- Knowledge lifecycle ownership;
- KnowledgeDocument immutability;
- tenant isolation;
- runtime retrieval scope;
- Control Plane Knowledge schema;
- management/internal trust boundaries;
- retrieval authority semantics;
- model-visible tool contract.

Implementation details that remain behind the documented ports and contracts do
not require an architecture revision.

Examples include:

- exact chunk-size constants;
- PyMuPDF extraction details;
- SQL query implementation;
- pgvector index tuning;
- MinIO object-key format;
- telemetry implementation.

## Implementation discipline

Domain and application behavior should be implemented test-first.

Every invariant in INVARIANTS.md that has executable behavior should normally be
protected by an automated test.

Do not weaken a documented invariant merely to preserve legacy implementation
behavior.
