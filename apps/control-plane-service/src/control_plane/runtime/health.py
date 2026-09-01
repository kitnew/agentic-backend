from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Readiness:
    postgres: bool
    control_plane_schema: bool
    nats: bool
    outbox_relay: bool

    @property
    def ready(self) -> bool:
        return (
            self.postgres
            and self.control_plane_schema
            and self.nats
            and self.outbox_relay
        )
