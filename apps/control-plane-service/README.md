## Control Plane service

This service owns Control Plane persistence. Backend must not directly query or
write Control Plane tables, and this service must not import Backend ORM models.

The service starts in `STARTING`, connects PostgreSQL, verifies the Control Plane
schema head, provisions the `CONTROL_PLANE_EVENTS` JetStream stream, and starts
the outbox relay before entering `READY`. Shutdown stops the relay, drains and
closes NATS, closes PostgreSQL, shuts down telemetry, and enters `STOPPED`.
`/health` is process liveness; `/ready` checks the lifecycle state, bounded live
PostgreSQL/JetStream pings, the dedicated Control Plane Alembic head, and the
relay runtime. An outbox backlog does not make the service unready.

Published and rollback lifecycle transactions insert
`configuration.component.published.v1` into
`control_plane.outbox_messages`. The relay publishes it to
`evt.configuration.component.published.v1` with `event_id` as `Nats-Msg-Id`.
Delivery is at least once; published rows are retained. Domain events are not
serialized by the NATS adapter.

Managed provider credentials are encrypted with AES-256-GCM using the
base64-encoded 32-byte `CONTROL_PLANE_ENCRYPTION_KEY`. The key is bootstrap
configuration only and is never stored in PostgreSQL. Each ciphertext records
its key ID, algorithm, nonce, and ciphertext for future key rotation.
Managed-resource changes publish `control_plane.managed_resource.changed.v1`
through the same outbox and JetStream relay; event payloads contain metadata
only. The relay orders only one resource identity at a time: component
revisions use revision number, while managed resources use their CAS generation.

Future execution provenance may record a configuration revision snapshot and
the resolved connection/deployment generations. Credential authorization stays
live: a later credential revocation always denies use, including from a prior
snapshot.

Tenant runtime intent is split into independent versioned components.
`runtime.architecture.policy` is an ordered allowlist: a future planner may
select only a listed architecture and must treat earlier entries as higher
priority; heuristics must not override either constraint.
`runtime.speech.overrides` stores architecture-neutral language and STT hints
plus optional cascade and realtime voice-namespace overrides. Neither component
resolves providers or deployments at publication time.

When Control Plane persistence is introduced, choose either a dedicated
`control_plane` schema on this PostgreSQL server or a dedicated application
database. Do not create shared Backend/Control Plane table ownership.
