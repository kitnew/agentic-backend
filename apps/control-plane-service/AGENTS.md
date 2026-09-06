# Control Plane Development Instructions

The target Control Plane architecture is explicitly designed and documented.

Before modifying Control Plane code, read:

- `../../docs/control-plane/README.md`
- `../../docs/control-plane/ARCHITECTURE.md`
- `../../docs/control-plane/CONTRACTS.md`
- `../../docs/control-plane/INVARIANTS.md`

If `../../docs/control-plane/REFACTOR_PLAN.md` exists and the task is part of the
Control Plane rewrite/refactor, read it as well.

These documents are the architectural source of truth.

The current implementation is evidence of current behavior and migration
constraints. It is NOT authoritative when it conflicts with the documented
target architecture.

## Architectural Boundaries

The Control Plane uses these domain building blocks:

- `VersionedComponent`
- `LiveComponent`
- `ManagedResource`
- `Catalog`
- `Registry`

Do not introduce another generic lifecycle/domain archetype unless explicitly
approved.

Repositories are persistence ports. They must not define HTTP or application
semantics.

Application Services own use-case orchestration and cross-object workflow
invariants.

HTTP handlers must remain thin adapters over Application Services.

## Configuration

The primary high-level configuration models are:

- `SystemConfiguration`
- `PlatformConfiguration`
- `TenantConfiguration`

High-level management workflows are primary.

They hide low-level component lifecycle and orchestration details from normal
`agentctl` and Admin Web workflows.

Low-level management APIs are expert/advanced surfaces for individual components,
catalog entries, managed resources, registries, history, rollback, and similar
operations.

Do not implement ordinary high-level workflows by forcing clients to orchestrate
multiple low-level component operations.

## Execution

Backend, Voice Agent, and Worker consume consumer-specific execution contracts.

They must not depend on:

- `ComponentKind`
- `ComponentAddress`
- draft/revision machinery
- repository details
- raw provider/credential graphs
- raw `ExecutionSnapshot` persistence structure

`ExecutionSnapshot` is an internal immutable persistence artifact.

Secrets must not be embedded in execution snapshots.
Secret-bearing execution material is late-bound.

The Worker has no direct Control Plane dependency unless the architecture
documentation is explicitly changed.

## HTTP Surfaces

Management:

- `/management/v1/*`

Internal service-to-service execution:

- `/internal/v1/*`

Operations:

- `/health`
- `/ready`

Do not introduce unscoped generic `/v1/*` endpoints.

Management and internal APIs must use structurally separate authentication
boundaries.

## Concurrency and Idempotency

Management concurrency follows documented HTTP semantics:

- reads return `ETag`
- state-changing operations use `If-Match` where applicable
- stale state returns `412 Precondition Failed`

Internal revision IDs, draft versions, and resource generations must not leak into
high-level management contracts merely to implement concurrency.

State-changing commands that require idempotency must follow the documented
`Idempotency-Key` semantics.

Do not create endpoint-specific concurrency or idempotency schemes.

## Transactions

Respect the documented transactional guarantees.

In particular:

- high-level configuration apply operations are atomic
- high-level publish operations are atomic
- individual ManagedResource mutations are atomic
- execution creation persists one complete immutable execution snapshot or none
- idempotency state commits atomically with its mutation
- do not hold database transactions open across external network validation calls

## Contracts

The Control Plane HTTP/OpenAPI contract is the external source of truth.

Do not make callers import Control Plane domain or persistence models.

Use shared/generated contract clients where applicable.

A breaking contract change requires explicit intent and corresponding consumer
migration.

## Change Discipline

Do not preserve legacy APIs merely because they already exist.

Do not delete or change legacy behavior merely because it differs from the target
architecture unless the current task includes that migration.

When target architecture, current behavior, and migration requirements conflict:

1. stop,
2. identify the conflict,
3. report the affected consumers/data,
4. request or derive an explicit migration decision before proceeding.

Do not introduce speculative future features while performing the refactor.