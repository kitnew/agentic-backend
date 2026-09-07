# Control Plane Architecture

This directory contains the frozen target architecture and semantic contracts for
the Control Plane refactor.

## Source of truth

Read in this order:

1. [ARCHITECTURE.md](./ARCHITECTURE.md)
   - domains
   - domain building blocks
   - repositories
   - application services
   - execution model

2. [SCHEMAS.md](./SCHEMAS.md)
   - canonical semantic payload schemas
   - component field ownership
   - managed-resource semantic shapes
   - action schemas
   - cross-schema reference rules
   - legacy-to-target semantic mapping

3. [CONTRACTS.md](./CONTRACTS.md)
   - consumers
   - management/internal interfaces
   - HTTP API
   - DTOs
   - concurrency
   - idempotency
   - errors
   - authorization
   - transactional guarantees
   - OpenAPI/shared-contract ownership

4. [INVARIANTS.md](./INVARIANTS.md)
   - non-negotiable architectural, domain, execution, and contract rules

## Authority

These documents define different aspects of the same frozen target:

- `ARCHITECTURE.md` defines **what exists and where responsibilities belong**.
- `SCHEMAS.md` defines **the canonical semantic fields and payload ownership**.
- `CONTRACTS.md` defines **how consumers interact with the Control Plane**.
- `INVARIANTS.md` defines **rules that implementations must not violate**.

They must remain mutually consistent.

If a proposed change requires these documents to disagree, the architecture change
must be made explicit before implementation.

## Status

The architecture described here is the target architecture for the current
Control Plane refactor.

The existing implementation may differ and must not be treated as the target
design when a discrepancy exists.

If the current implementation conflicts with these documents:

1. treat the implementation as evidence of current/legacy behavior;
2. identify the affected behavior, data, and consumers;
3. do not silently adapt the target architecture or schemas to match legacy code;
4. make the migration decision explicit before changing architectural semantics.

Legacy field presence is not sufficient reason to preserve a field in the target
schema.

Likewise, an existing consumer requirement must not be dropped without first
identifying how that behavior is represented in the target architecture.

Changes to the target architecture itself must be intentional and reflected in the
relevant documents.

## Implementation Discipline

Control Plane domain and application behavior follows test-driven development.

Configuration and execution state are particularly sensitive to lifecycle,
reference, schema, concurrency, idempotency, and transactional invariants. These
rules should be expressed as executable tests before or together with their
implementation rather than being left implicit in code.

For new or changed domain/application behavior:

1. identify the invariant or use-case behavior being implemented;
2. write or update the test that expresses the expected behavior;
3. verify that the test fails for the intended reason when introducing new
   behavior;
4. implement the smallest change required to satisfy it;
5. refactor only while preserving the relevant test suite.

For schema work, tests should be derived from both `SCHEMAS.md` and
`INVARIANTS.md`.

Tests should cover the relevant boundaries, including where applicable:

- valid lifecycle transitions;
- forbidden lifecycle transitions;
- schema validation and unknown-field rejection;
- reference and ownership validation;
- draft / publish / rollback behavior;
- immediate activation of live state;
- runtime override and inheritance semantics;
- optimistic concurrency;
- atomic application-service operations;
- idempotency-sensitive mutations;
- execution snapshot immutability;
- secret isolation and late binding;
- consumer projection boundaries;
- action definition and availability consistency.

A domain or contract invariant documented in `INVARIANTS.md` should normally have
an automated test that demonstrates and protects it.

A semantic rule documented in `SCHEMAS.md` should normally have a schema/domain test
that protects its field shape, validation behavior, or reference semantics.

Do not weaken or delete an invariant/schema test merely to make an implementation
change pass.

If intended behavior has changed, update the source-of-truth documentation
explicitly first.
