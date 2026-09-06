# Control Plane Architecture

This directory contains the frozen target architecture for the Control Plane
refactor.

## Source of truth

Read in this order:

1. [ARCHITECTURE.md](./ARCHITECTURE.md)
   - domains
   - domain building blocks
   - repositories
   - application services
   - execution model

2. [CONTRACTS.md](./CONTRACTS.md)
   - consumers
   - management/internal interfaces
   - HTTP API
   - DTOs
   - concurrency
   - idempotency
   - errors
   - authorization
   - transactional guarantees

3. [INVARIANTS.md](./INVARIANTS.md)
   - non-negotiable architectural and domain rules

## Status

The architecture described here is the target architecture for the current
Control Plane refactor.

The existing implementation may differ and must not be treated as the target
design when a discrepancy exists.

If the current implementation conflicts with these documents:

1. treat the implementation as evidence of current/legacy behavior;
2. identify the affected behavior, data, and consumers;
3. do not silently adapt the target architecture to match the legacy code;
4. make the migration decision explicit before changing architectural semantics.

Changes to the architecture itself must be intentional and reflected in these
documents.

## Implementation Discipline

Control Plane implementation follows test-driven development where domain and
application behavior is involved.

Configuration and execution state are particularly sensitive to lifecycle,
reference, concurrency, and transactional invariants. These invariants should be
captured by tests before or together with their implementation rather than being
left implicit in code.

For new or changed domain/application behavior:

1. identify the invariant or use-case behavior being implemented;
2. write or update the test that expresses the expected behavior;
3. verify that the test fails for the intended reason when introducing new
   behavior;
4. implement the smallest change required to satisfy it;
5. refactor only while preserving the full test suite.

Tests should cover the relevant boundaries, including where applicable:

- valid lifecycle transitions;
- forbidden lifecycle transitions;
- draft / publish / rollback behavior;
- immediate activation of live state;
- reference and ownership validation;
- optimistic concurrency;
- atomic application-service operations;
- idempotency-sensitive mutations;
- execution snapshot immutability;
- secret isolation and late binding;
- consumer projection boundaries.

A domain invariant documented in `INVARIANTS.md` should normally have an
automated test that demonstrates and protects it.

Do not weaken or delete an invariant test merely to make an implementation
change pass. If the intended behavior has changed, update the architecture and
invariant documentation explicitly first.