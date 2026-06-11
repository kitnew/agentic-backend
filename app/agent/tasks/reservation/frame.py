from typing import Any

from pydantic import BaseModel, Field


class ReservationFrame(BaseModel):
    guest_name: str | None = None
    date: str | None = None
    time: str | None = None
    party_size: int | None = None
    phone: str | None = None
    notes: str | None = None
    raw_messages: list[str] = Field(default_factory=list)


def merge_reservation_frame(
    existing_frame: dict[str, Any] | None,
    field_updates: dict[str, Any] | None,
) -> ReservationFrame:
    frame = ReservationFrame.model_validate(existing_frame or {})
    for field_name, value in (field_updates or {}).items():
        if hasattr(frame, field_name) and _has_value(value):
            setattr(frame, field_name, value)
    return frame


def clean_reservation_frame(frame: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in frame.items() if _has_value(value)}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True
