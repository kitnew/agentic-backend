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

When Control Plane persistence is introduced, choose either a dedicated
`control_plane` schema on this PostgreSQL server or a dedicated application
database. Do not create shared Backend/Control Plane table ownership.
