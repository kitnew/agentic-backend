from dataclasses import dataclass
from datetime import datetime

from control_plane.domain.components import ComponentAddress


@dataclass(frozen=True, slots=True)
class LiveComponentState[T]:
    address: ComponentAddress
    value: T
    schema_version: int
    generation: int
    updated_at: datetime
    updated_by: str
