from typing import Any
from datetime import datetime

from app.agent.contracts.state import TaskValidationError
from app.agent.tasks.reservation.frame import ReservationFrame


REQUIRED_FIELDS_BY_BUSINESS_TYPE = {
    "restaurant": ["guest_name", "date", "time", "party_size", "phone"],
    "hostel": ["guest_name", "check_in_date", "check_out_date", "guests_count", "phone"],
}


FIELD_LABELS = {
    "guest_name": "meno",
    "date": "dátum",
    "time": "čas",
    "party_size": "počet osôb",
    "phone": "telefónne číslo",
    "check_in_date": "dátum príchodu",
    "check_out_date": "dátum odchodu",
    "guests_count": "počet hostí",
}


def get_required_fields(business_type: str) -> list[str]:
    return REQUIRED_FIELDS_BY_BUSINESS_TYPE.get(
        business_type,
        REQUIRED_FIELDS_BY_BUSINESS_TYPE["restaurant"],
    )


def get_required_fields_from_tenant(tenant_context: dict[str, Any]) -> list[str]:
    reservation_config = tenant_context.get("reservation") or {}
    required_fields = reservation_config.get("required_fields") or []
    if required_fields:
        return required_fields
    return get_required_fields(tenant_context.get("business_type", "restaurant"))


def get_missing_fields(frame: ReservationFrame | dict[str, Any], business_type: str) -> list[str]:
    frame_data = frame if isinstance(frame, dict) else frame.model_dump(mode="json")
    return [field for field in get_required_fields(business_type) if not has_value(frame_data.get(field))]


def get_missing_fields_from_tenant(
    frame: dict[str, Any],
    tenant_context: dict[str, Any],
) -> list[str]:
    return [
        field_name
        for field_name in get_required_fields_from_tenant(tenant_context)
        if not has_value(frame.get(field_name))
    ]


def is_ready_to_submit(frame: ReservationFrame | dict[str, Any], business_type: str) -> bool:
    return not get_missing_fields(frame, business_type)


def merge_missing_fields(
    missing_fields: list[str],
    invalid_fields: list[str],
) -> list[str]:
    merged = list(missing_fields)
    for field_name in invalid_fields:
        if field_name not in merged:
            merged.append(field_name)
    return merged


def validate_structured_business_rules(
    frame: dict[str, Any],
    tenant_context: dict[str, Any],
) -> list[TaskValidationError]:
    errors = []
    time_error = validate_structured_opening_hours(frame, tenant_context)
    if time_error is not None:
        errors.append(time_error)
    return errors


def validate_structured_opening_hours(
    frame: dict[str, Any],
    tenant_context: dict[str, Any],
) -> TaskValidationError | None:
    opening_hours = (tenant_context.get("reservation") or {}).get("opening_hours") or []
    requested_time = frame.get("time")
    if not opening_hours or not has_value(requested_time):
        return None

    parsed_requested_time = _parse_hhmm(str(requested_time))
    if parsed_requested_time is None:
        return None

    for time_range in opening_hours:
        start = _parse_hhmm(str(time_range.get("start", "")))
        end = _parse_hhmm(str(time_range.get("end", "")))
        if start is None or end is None:
            continue
        if start <= parsed_requested_time <= end:
            return None

    return TaskValidationError(
        field="time",
        code="out_of_hours",
        message="Requested time is outside of reservation opening hours.",
    )


def structured_opening_hours_configured(tenant_context: dict[str, Any]) -> bool:
    return bool((tenant_context.get("reservation") or {}).get("opening_hours") or [])


def _parse_hhmm(value: str):
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True
