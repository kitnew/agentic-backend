from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Readiness:
    postgres: bool
    nats: bool

    @property
    def ready(self) -> bool:
        return self.postgres and self.nats
