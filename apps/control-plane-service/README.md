## Control Plane service

This service owns Control Plane persistence. Backend must not directly query or
write Control Plane tables, and this service must not import Backend ORM models.

The service starts in `STARTING`, connects PostgreSQL, then NATS, and only then
enters `READY`. Shutdown drains NATS, closes NATS, closes PostgreSQL, shuts down
telemetry, and enters `STOPPED`. `/health` is process liveness; `/ready` checks
the lifecycle state, bounded live PostgreSQL/NATS pings, and that the dedicated
Control Plane Alembic revision matches the application migration head.

Messaging is transport-only: application code supplies an `OutboundMessage`
containing a subject and serialized bytes. Domain events are not serialized by
the NATS adapter. No business subjects exist yet.

When Control Plane persistence is introduced, choose either a dedicated
`control_plane` schema on this PostgreSQL server or a dedicated application
database. Do not create shared Backend/Control Plane table ownership.
