# Control Plane Invariants

> Status: **target architecture invariant set**
>
> This document contains the non-negotiable rules of the Control Plane target
> architecture.
>
> It is intentionally concise and normative. It does not describe full workflows,
> endpoint catalogs, or implementation details.
>
> If implementation, tests, migrations, or legacy behavior conflict with an invariant
> in this document, the conflict must be made explicit rather than silently resolved
> in favor of the current code.
>
> Related documents:
>
> - [`ARCHITECTURE.md`](./ARCHITECTURE.md) — domain model, building blocks,
>   repositories, application services, execution architecture.
> - [`CONTRACTS.md`](./CONTRACTS.md) — interfaces, HTTP APIs, DTOs, concurrency,
>   idempotency, authorization, errors, transactional guarantees.

---

## Table of Contents

- [1. General architectural invariants](#1-general-architectural-invariants)
- [2. VersionedComponent invariants](#2-versionedcomponent-invariants)
- [3. LiveComponent invariants](#3-livecomponent-invariants)
- [4. ManagedResource invariants](#4-managedresource-invariants)
- [5. Catalog invariants](#5-catalog-invariants)
- [6. Registry invariants](#6-registry-invariants)
- [7. Reference and ownership invariants](#7-reference-and-ownership-invariants)
- [8. Repository invariants](#8-repository-invariants)
- [9. Application service invariants](#9-application-service-invariants)
- [10. Configuration invariants](#10-configuration-invariants)
  - [10.1 SystemConfiguration](#101-systemconfiguration)
  - [10.2 PlatformConfiguration](#102-platformconfiguration)
  - [10.3 TenantConfiguration](#103-tenantconfiguration)
- [11. Credential invariants](#11-credential-invariants)
- [12. Provider invariants](#12-provider-invariants)
- [13. Telephony invariants](#13-telephony-invariants)
- [14. Integration invariants](#14-integration-invariants)
- [15. Execution invariants](#15-execution-invariants)
- [16. Consumer boundary invariants](#16-consumer-boundary-invariants)
- [17. HTTP and contract invariants](#17-http-and-contract-invariants)
- [18. Concurrency invariants](#18-concurrency-invariants)
- [19. Idempotency invariants](#19-idempotency-invariants)
- [20. Transactional invariants](#20-transactional-invariants)
- [21. Authorization invariants](#21-authorization-invariants)
- [22. Error-model invariants](#22-error-model-invariants)
- [23. OpenAPI and shared-contract invariants](#23-openapi-and-shared-contract-invariants)
- [24. Change-discipline invariants](#24-change-discipline-invariants)

---

## 1. General architectural invariants

1. The Control Plane is the authority for configuration state, managed runtime
   resources, and execution materialization within its documented boundaries.

2. The fundamental domain building blocks are limited to:
   - `VersionedComponent`
   - `LiveComponent`
   - `ManagedResource`
   - `Catalog`
   - `Registry`

3. New generic lifecycle/domain archetypes must not be introduced unless the target
   architecture is explicitly revised.

4. `SystemConfiguration`, `PlatformConfiguration`, and `TenantConfiguration` are
   semantic aggregates/views over lower-level objects. They are not new persistence
   primitives.

5. There is no generic `DesiredState` domain primitive. "Desired" objects are
   application/API input models representing requested semantic state.

6. Transport, application, domain, and persistence responsibilities remain separate.

7. Current implementation structure is not authoritative when it conflicts with the
   documented target architecture.

---

## 2. VersionedComponent invariants

1. A versioned component is identified by stable `(kind, scope)`.

2. At most one mutable draft exists for a versioned component address.

3. Published revisions are immutable.

4. Revision history is append-only.

5. Editing a component never mutates an already-published revision.

6. Draft changes are not active until explicit publish.

7. Publishing a draft creates a new immutable revision and makes that revision active.

8. Discarding a draft does not alter revision history.

9. Rollback does not rewrite or delete historical revisions.

10. Rollback preserves provenance of the revision being restored.

11. Schema version belongs to component definition / stored component state, not to
    arbitrary caller choice.

12. A component kind may only exist in scopes allowed by its
    `ComponentDefinition`.

13. Invalid values must not be persisted as valid drafts/revisions.

14. Versioned-component concurrency is optimistic.

---

## 3. LiveComponent invariants

1. A live component is identified by stable `(kind, scope)`.

2. A live component has exactly one current value per address.

3. Updating a live component takes effect immediately after successful commit.

4. Live components have:
   - no draft,
   - no revision history,
   - no publish step,
   - no rollback lifecycle equivalent to `VersionedComponent`.

5. Live-component concurrency is optimistic.

6. Internal generation/version mechanics must not change the semantic lifecycle:
   live means one immediately effective current value.

7. Complex structured values may still be live components. Structural richness does
   not imply versioned lifecycle semantics.

---

## 4. ManagedResource invariants

1. A managed resource has independent resource identity.

2. Managed resources own resource-specific lifecycle semantics.

3. A managed resource is not modeled as a `VersionedComponent` or `LiveComponent`
   merely because it has mutable fields.

4. Resource ownership/scope is immutable unless explicitly documented otherwise for
   that resource type.

5. Resource keys that are defined as stable identity keys are immutable after
   creation unless explicitly documented otherwise.

6. Disable/revoke operations do not silently delete references.

7. Deleting referenced managed resources is not an implicit consequence of changing
   configuration.

8. Managed-resource mutations are optimistic-concurrency protected.

9. Managed-resource state changes are atomic per command.

---

## 5. Catalog invariants

1. Catalogs are operator-managed.

2. Catalog entries have stable semantic keys.

3. Catalogs exist for:
   - discovery,
   - metadata,
   - reference validation.

4. A catalog entry may own or be associated with other domain objects, but the
   catalog itself does not redefine their lifecycle.

5. `ProfilePrompt` remains a `VersionedComponent` under
   `ProfileScope(profile_key)`.

6. `InteractionPrompt` remains a `VersionedComponent` under
   `InteractionModeScope(mode_key)`.

7. Editing catalog metadata must not silently rewrite associated prompt revision
   history.

---

## 6. Registry invariants

1. Registries are code/implementation-owned.

2. Registry entries have stable keys.

3. Registries are read-only from the operator perspective.

4. Registry entries have no draft/publish lifecycle.

5. Runtime/configuration values that reference an implementation kind must resolve
   to an existing compatible registry entry.

6. `ComponentDefinitionRegistry` is authoritative for:
   - component kind existence,
   - value schema,
   - schema version,
   - allowed scopes,
   - validation metadata.

7. `Architecture` values must resolve through `ArchitectureRegistry`.

8. Provider kinds, deployment kinds, and integration kinds must resolve through
   their respective registries.

---

## 7. Reference and ownership invariants

1. A reference represents dependency, not ownership.

2. A reference must resolve before the referencing state is considered valid where
   the use case requires referential validity.

3. Referenced object scope/ownership must be compatible with the referencing object.

4. References do not cause implicit cascade deletion.

5. References must not silently retarget to a different object.

6. Tenant-owned resources must not reference tenant-owned credentials belonging to
   another tenant.

7. Platform provider connections may only reference credentials allowed by the
   provider domain's documented scope rules.

8. `ProfileReference` must resolve to an existing usable platform profile.

9. `ActionsAvailability` may only refer to actions that exist in the corresponding
   `ActionsDefinition`.

10. Execution materialization must validate references used by the execution before
    returning a successful execution.

---

## 8. Repository invariants

1. Repositories are persistence ports, not application services.

2. Repositories contain no HTTP semantics.

3. Repositories do not define business lifecycle rules.

4. Repositories hide persistence implementation details.

5. Repositories operate on domain/application persistence models rather than HTTP
   request/response DTOs.

6. Replacing a repository implementation must not require changing the semantic
   contract of the application service using it.

7. Repository interfaces must not become a backdoor for bypassing application-level
   invariants.

---

## 9. Application service invariants

1. Application services execute application use cases.

2. Application services orchestrate repositories, domain objects, catalogs, and
   registries.

3. Application services own transaction boundaries for their use cases.

4. Application services contain no HTTP-specific behavior.

5. HTTP handlers are thin adapters over application services.

6. Application services return application results / DTO-ready semantic results,
   not persistence implementation details.

7. Cross-object validation required by a use case belongs at application-service
   orchestration level when it cannot be enforced by one domain object alone.

8. Normal high-level workflows must not require the caller to orchestrate multiple
   low-level application services manually.

---

## 10. Configuration invariants

### 10.1 SystemConfiguration

1. `SystemConfiguration` is composed of system-scoped live components.

2. Current system configuration includes:
   - `STTDefaults`
   - `LLMDefaults`
   - `TTSDefaults`
   - `RealtimeDefaults`
   - `Policies`

3. System configuration changes are immediately active after successful apply.

4. `SystemConfiguration` has no publish lifecycle.

5. `SystemConfiguration.apply` is atomic.

6. Provider/model-specific setting validity must be enforced through component
   schemas, registries, capability metadata, or semantic validation; unsupported
   combinations must not be accepted merely because fields exist structurally.

---

### 10.2 PlatformConfiguration

1. `PlatformConfiguration` combines:
   - platform/profile/interaction-mode versioned prompts,
   - operator-managed catalogs.

2. Catalog metadata changes become active on apply.

3. Versioned prompt changes become drafts on apply.

4. Versioned prompt changes become active only on publish.

5. `PlatformConfiguration.apply` is atomic.

6. `PlatformConfiguration.publish` is atomic.

7. A failed publish must not leave only a subset of pending platform prompt changes
   published.

8. High-level platform configuration does not expose revision orchestration as part
   of the normal workflow.

---

### 10.3 TenantConfiguration

1. `TenantConfiguration` combines tenant-scoped versioned and live components.

2. Versioned tenant components:
   - `TenantPrompt`
   - `Knowledge`
   - `AgentPersonality`
   - `BusinessInfo`
   - `ActionsDefinition`

3. Live tenant components:
   - `Architecture`
   - `ProfileReference`
   - `RuntimeOverrides`
   - `ActionsAvailability`

4. Applying tenant configuration:
   - updates live components immediately,
   - saves changed versioned components as drafts.

5. Publishing tenant configuration publishes versioned components only.

6. Live components are already active and are not republished.

7. `TenantConfiguration.apply` is atomic.

8. `TenantConfiguration.publish` is atomic.

9. A failed high-level apply must not leave a partially applied semantic tenant
   configuration.

10. A failed high-level publish must not leave only a subset of the pending tenant
    drafts published.

11. `plan` performs validation and diffing but does not mutate state.

12. High-level tenant configuration validation includes cross-object/reference
    checks required for a coherent configuration.

---

## 11. Credential invariants

1. Credential secret material is never returned by normal management read APIs.

2. A credential has an independent lifecycle.

3. Credential scope is immutable.

4. Rotating a credential creates a new immutable secret version.

5. Rotation does not rewrite historical secret versions.

6. Exactly one secret version is active after successful rotation.

7. Revoked credentials cannot be materialized for runtime use.

8. Revoking a credential does not delete references to it.

9. Secret values are protected at rest.

10. Secret version internals remain hidden from ordinary consumers unless explicitly
    required for internal audit/diagnostics.

---

## 12. Provider invariants

1. `ProviderConnection.provider_kind` must exist in `ProviderKindRegistry`.

2. A provider connection must reference a credential valid for the provider domain's
   scope rules.

3. An enabled provider connection requires a usable, non-revoked credential.

4. `ModelDeployment.connection_ref` must resolve to an existing provider connection.

5. `ModelDeployment.deployment_kind` must exist in `DeploymentKindRegistry`.

6. Deployment configuration must be valid for its deployment kind.

7. Deployment capability metadata must be consistent with the deployment kind.

8. An enabled model deployment requires a usable provider connection.

9. Provider/deployment validation may perform external network checks, but external
   validation must not hold a database transaction open.

10. Runtime consumers do not receive the raw provider/credential resource graph.

---

## 13. Telephony invariants

1. Phone numbers are normalized before identity/uniqueness comparisons.

2. One normalized inbound phone number may have at most one enabled assignment.

3. `PhoneNumberAssignment.tenant_id` is immutable.

4. `HandoffDestination.tenant_id` is immutable.

5. Handoff destination key is unique within a tenant.

6. Handoff destination enable/disable state is live operational state.

7. Inbound phone resolution returns semantic routing information rather than raw
   repository state.

8. A handoff materialization request must resolve to a destination belonging to the
   execution tenant/context.

9. Disabled handoff destinations are not usable execution destinations.

---

## 14. Integration invariants

1. `IntegrationConnection.tenant_id` is immutable.

2. Integration key is unique within a tenant.

3. `integration_kind` must exist in `IntegrationKindRegistry`.

4. Integration config must be valid for its `integration_kind`.

5. If a credential reference is present:
   - the credential must exist,
   - the credential must belong to the same tenant when tenant-scoped,
   - the credential must not be revoked when usability is required.

6. Integration validation may perform external network/authentication checks.

7. External validation does not hold a database transaction open.

8. Runtime execution uses semantic integration keys / execution material, not raw
   integration connection IDs as the consumer contract.

9. Integration secret material is late-bound.

---

## 15. Execution invariants

1. Execution creation resolves one coherent effective state.

2. Successful execution creation persists one complete immutable execution snapshot.

3. Execution creation is all-or-nothing.

4. `ExecutionSnapshot` is an internal persistence artifact.

5. Runtime consumers do not receive raw `ExecutionSnapshot`.

6. An existing execution snapshot is never silently re-resolved.

7. All consumer execution contexts for the same execution are derived from the same
   immutable snapshot.

8. Execution snapshots contain no secret material.

9. Secret-bearing material is late-bound.

10. Late-bound material must belong to the same execution tenant/context.

11. References required by the execution are validated during execution
    materialization.

12. Consumer-specific projections contain only the information required by that
    consumer.

13. `execution_id` is an opaque transport handle. Consumers must not infer persistence
    structure from it.

14. Runtime projection contracts do not expose:
    - `ComponentKind`
    - `ComponentAddress`
    - component draft state
    - component revision choreography
    - repository details
    - raw provider/credential graph structure.

---

## 16. Consumer boundary invariants

1. Backend receives `BackendExecutionContext`, not raw Control Plane state.

2. Voice Agent receives `VoiceExecutionContext` through Backend.

3. Voice Agent may call Control Plane directly only for explicitly authorized
   late-bound runtime material, such as runtime secrets.

4. Worker receives `WorkerExecutionContext` through Backend.

5. Worker has no direct Control Plane dependency in the target architecture.

6. Backend may pass Voice/Worker projections through, but must not reconstruct them
   from raw Control Plane persistence state.

7. Consumers must not own duplicated copies of Control Plane lifecycle logic.

8. Consumer contracts are semantic and consumer-specific.

---

## 17. HTTP and contract invariants

1. Management API lives under `/management/v1/*`.

2. Internal service-to-service API lives under `/internal/v1/*`.

3. Operational probes are `/health` and `/ready`.

4. The target contract must not introduce a generic mixed-purpose `/v1/*` surface.

5. High-level management is the primary operator contract.

6. Low-level management is an expert/advanced contract.

7. High-level management DTOs do not expose component revision IDs, draft versions,
   or resource generations solely for concurrency.

8. Normal consumer contracts do not expose persistence-oriented execution snapshot
   terminology.

9. Tenant-owned resources use tenant-scoped paths where the contract has frozen that
   ownership in the URL.

10. Normal credential reads never expose secrets.

---

## 18. Concurrency invariants

1. Management concurrency uses opaque HTTP `ETag` values.

2. Mutations use `If-Match` where concurrency protection applies.

3. Stale concurrency tokens produce `412 Precondition Failed`.

4. `412` is reserved for concurrency/precondition failure, not general domain
   conflict.

5. High-level ETags represent the complete semantic configuration state relevant to
   that high-level operation.

6. Low-level ETags represent one independently managed object.

7. Clients treat ETags as opaque.

8. Internal generation/revision counters remain implementation details unless a
   separate explicit contract requires them for observation/audit.

---

## 19. Idempotency invariants

1. State-changing commands documented as idempotent-retry-safe require
   `Idempotency-Key`.

2. Idempotency key scope includes at least:
   - authenticated principal,
   - operation,
   - key.

3. Same key + same operation + same principal + same request replays the same logical
   result.

4. Same idempotency key reused with a different request produces a domain conflict.

5. Idempotency lookup occurs before concurrency validation on retry.

6. Mutation state and idempotency replay state commit atomically.

7. Execution creation must not create duplicate executions because a successful
   response was lost and retried.

8. Credential rotation must not create duplicate secret versions because of retry.

9. Publish must not repeat the semantic publication because of retry.

10. Read-only/materialization operations that do not mutate persistent state do not
    require idempotency keys.

---

## 20. Transactional invariants

1. `SystemConfiguration.apply` is atomic.

2. `TenantConfiguration.apply` is atomic.

3. `TenantConfiguration.publish` is atomic.

4. `PlatformConfiguration.apply` is atomic.

5. `PlatformConfiguration.publish` is atomic.

6. Every individual managed-resource mutation is atomic.

7. Execution creation / snapshot persistence is atomic.

8. Idempotency result persistence is atomic with the mutation it protects.

9. Database transactions are not held open across external network calls.

10. A transaction boundary follows one semantic use case, not one arbitrary HTTP or
    repository operation.

---

## 21. Authorization invariants

1. `/management/v1/*` requires a management principal.

2. `/internal/v1/*` requires a service principal.

3. Management and internal authentication boundaries are structurally separate.

4. Backend has only the internal scopes required for:
   - telephony resolution,
   - execution creation,
   - execution projection reads,
   - integration/handoff materialization.

5. Backend does not receive management privileges.

6. Voice Agent receives only the scope(s) required for direct late-bound runtime
   materialization.

7. Worker has no direct Control Plane credentials in the target architecture.

8. Audit actor identity comes from the authenticated principal, not caller-supplied
   body fields.

9. Credential-management privileges are distinct from ordinary configuration write
   privileges.

---

## 22. Error-model invariants

1. All HTTP surfaces use the shared structured `ErrorResponse` model.

2. Validation details use structured `ValidationIssue` entries.

3. HTTP status semantics remain consistent across domains.

4. `404` means the addressed/read resource is absent.

5. `409` means a domain/state conflict.

6. `412` means concurrency/precondition conflict.

7. `422` means the submitted semantic value/reference is invalid.

8. Internal unexpected failures are not disguised as semantic validation failures.

9. Error responses include a request identifier suitable for diagnostics.

---

## 23. OpenAPI and shared-contract invariants

1. OpenAPI is the machine-readable source of truth for the HTTP contract.

2. Contract schemas are not independently redefined in every consumer.

3. Generated/shared clients are preferred over handwritten duplicate transport
   models.

4. Control Plane domain and persistence objects are not exported as shared transport
   contracts.

5. Breaking OpenAPI changes require explicit intent.

6. Breaking changes require coordinated migration of affected consumers.

7. Contract generation must preserve the management/internal boundary.

---

## 24. Change-discipline invariants

1. Do not introduce abstractions solely to preserve legacy structure.

2. Do not preserve legacy APIs indefinitely merely because they already exist.

3. Do not remove legacy behavior solely because it differs from target architecture
   unless the current migration slice explicitly includes that behavior.

4. If target architecture, legacy behavior, and migration requirements conflict:
   - identify the conflict,
   - identify affected consumers/data,
   - make the migration decision explicit.

5. No speculative future feature should be introduced as part of an unrelated
   refactor.

6. A code change that violates an invariant requires an explicit architecture change,
   not a silent exception.

7. Tests must not lock in known legacy architecture when the task is explicitly
   migrating to the target architecture.

8. Documentation and OpenAPI must be updated together with intentional contract or
   architecture changes.

---

## Appendix: Short Codex checklist

Before accepting a Control Plane change, verify:

```text
[ ] Does it preserve the five core building blocks?
[ ] Does it keep high-level management primary?
[ ] Does it avoid leaking persistence/lifecycle internals to consumers?
[ ] Are versioned vs live lifecycle semantics preserved?
[ ] Are references validated without changing ownership semantics?
[ ] Are secrets excluded from snapshots and normal reads?
[ ] Is execution immutable once created?
[ ] Are consumer projections derived from one execution snapshot?
[ ] Are transaction boundaries semantic and atomic?
[ ] Is ETag/If-Match used instead of bespoke public version counters?
[ ] Is idempotency safe for retry-sensitive mutations?
[ ] Are management and internal auth boundaries separated?
[ ] Does OpenAPI remain the transport contract source of truth?
[ ] If legacy behavior conflicts, was the migration decision made explicit?
```
