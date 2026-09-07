# Control Plane Development Instructions

The target Control Plane architecture and semantic model are explicitly designed
and documented.

Before modifying Control Plane code, read:

- `../../docs/control-plane/README.md`
- `../../docs/control-plane/ARCHITECTURE.md`
- `../../docs/control-plane/SCHEMAS.md`
- `../../docs/control-plane/CONTRACTS.md`
- `../../docs/control-plane/INVARIANTS.md`

If `../../docs/control-plane/REFACTOR_PLAN.md` exists and the task is part of the
Control Plane rewrite/refactor, read it as well.

These documents are the architectural and semantic source of truth.

The current implementation is evidence of current behavior and migration
constraints. It is NOT authoritative when it conflicts with the documented target
architecture or schemas.

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

## Semantic Schemas

`SCHEMAS.md` is authoritative for semantic payload ownership and canonical target
fields.

Do not:

- preserve a legacy field merely because current code or YAML contains it;
- move a field to a different target component because that is easier to implement;
- duplicate provider/model/resource identity inside runtime configuration;
- expose managed-resource IDs where the target contract defines semantic references;
- introduce speculative fields for future behavior;
- silently keep unsupported legacy semantics.

When implementation fields do not map cleanly to `SCHEMAS.md`, report the mismatch
instead of inventing an implicit mapping.

Unknown fields must be rejected where the target schema specifies
`additionalProperties: false`.

Provider/model identity belongs to `ProviderConnection` / `ModelDeployment`, not
duplicated runtime configuration.

Runtime override inheritance, action availability, integration-key references,
agent identity, localization ownership, and other cross-schema rules must follow
`SCHEMAS.md`.

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

All consumer projections for one execution must derive from the same immutable
execution snapshot.

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

## Test-Driven Development

Domain and application behavior must be developed test-first.

For new or changed behavior:

1. identify the relevant rule in `SCHEMAS.md`, `CONTRACTS.md`, or `INVARIANTS.md`;
2. write or update the test that expresses that behavior;
3. verify the test fails for the intended reason when introducing new behavior;
4. implement the smallest change required to make it pass;
5. refactor only while preserving the relevant test suite.

Important schema/domain invariants must not exist only as comments or implicit code
behavior.

Tests should protect, where applicable:

- component lifecycle semantics;
- schema validation;
- unknown-field rejection;
- reference/scope validation;
- live-state activation;
- draft/publish/rollback behavior;
- runtime override inheritance;
- action definition/availability consistency;
- concurrency;
- idempotency;
- transaction atomicity;
- execution immutability;
- late-bound secrets;
- consumer boundary projections.

Do not weaken or delete an invariant test merely to make implementation easier.

If a test conflicts with the frozen target documentation, determine whether the
test represents legacy behavior before changing either side.

## Contracts

The Control Plane HTTP/OpenAPI contract is the external source of truth.

Do not make callers import Control Plane domain or persistence models.

Use shared/generated contract clients where applicable.

A breaking contract change requires explicit intent and corresponding consumer
migration.

Semantic payloads exposed through OpenAPI must remain consistent with
`SCHEMAS.md`.

## Change Discipline

Do not preserve legacy APIs merely because they already exist.

Do not delete or change legacy behavior merely because it differs from the target
architecture unless the current task includes that migration.

Do not introduce compatibility layers unless a current migration slice actually
requires them.

When target architecture, target schemas, current behavior, and migration
requirements conflict:

1. stop;
2. identify the conflict;
3. identify affected consumers/data;
4. report which source-of-truth rule is involved;
5. make the migration decision explicit before proceeding.

Do not introduce speculative future features while performing the refactor.

Do not modify unrelated architecture or semantics as part of a scoped
implementation task.
