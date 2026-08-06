import json
import os
import socket
from datetime import date
from typing import Any
from unicodedata import normalize
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.schemas import TenantContext


_PAYLOAD_SOURCES = {
    "guest_name",
    "booked_name",
    "check_in",
    "check_out",
    "original_check_in",
    "original_check_out",
    "change",
    "reason",
    "caller_number",
    "reservation_phone",
    "room_type_code",
    "room_count",
    "room_count_text",
}


class MakeWebhookProvider:
    provider_name = "make_webhook"
    default_timeout_seconds = 15

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        config = tenant_context.capabilities[capability_request.name].config
        if not valid_webhook_config(config):
            return self._failure(capability_request.name, "invalid_webhook_config")
        url = config.get("webhook_url")
        timeout = config.get("timeout_seconds", self.default_timeout_seconds)
        payload = _payload(tenant_context, capability_request, config)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        api_key_env = config.get("webhook_api_key_env")
        if api_key_env and (api_key := os.getenv(api_key_env)):
            headers["x-make-apikey"] = api_key
        if idempotency_key := (capability_request.metadata or {}).get("idempotency_key"):
            headers["Idempotency-Key"] = idempotency_key

        try:
            with urlopen(  # noqa: S310 - URL is tenant-admin configuration
                Request(
                    url,
                    data=json.dumps(payload, default=str).encode("utf-8"),
                    headers=headers,
                    method="POST",
                ),
                timeout=timeout,
            ) as response:
                status = response.status
                body = response.read()
        except (socket.timeout, TimeoutError):
            return self._failure(capability_request.name, "webhook_timeout")
        except HTTPError as exc:
            return self._failure(capability_request.name, f"webhook_http_{exc.code}")
        except (OSError, URLError) as exc:
            return self._failure(
                capability_request.name,
                f"webhook_request_failed:{exc.__class__.__name__}",
            )

        if status >= 400:
            return self._failure(capability_request.name, f"webhook_http_{status}")

        response_format = config.get("response_format")
        if response_format == "availability_text":
            try:
                response_text = body.decode("utf-8").strip()
            except UnicodeDecodeError:
                return self._failure(capability_request.name, "invalid_webhook_response")
            if not response_text:
                return self._failure(capability_request.name, "invalid_webhook_response")
            response_payload = {"status": response_text}
            if capability_request.name == "reservation.check_availability":
                response_payload.update(
                    {
                        "availability_state": _availability_state(response_text),
                        "check_in": capability_request.input.get("check_in"),
                        "check_out": capability_request.input.get("check_out"),
                        "requested_room_type": capability_request.input.get("room_type"),
                        "allocated_room_type": capability_request.input.get("room_type"),
                        "requested_rooms": capability_request.input.get("room_count"),
                    }
                )
        elif response_format == "acknowledgement":
            response_payload = {"status": "submitted"}
        else:
            try:
                response_payload = json.loads(body.decode("utf-8")) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._failure(capability_request.name, "invalid_webhook_response")

        if not isinstance(response_payload, dict):
            response_payload = {"response": response_payload}
        response_status = response_payload.get("status")
        if isinstance(response_status, str):
            response_status = response_status.casefold()
        result_status = {
            "skipped": CapabilityStatus.SKIPPED,
            "failed": CapabilityStatus.FAILED,
            "error": CapabilityStatus.FAILED,
        }.get(response_status, CapabilityStatus.SUCCESS)
        output = response_payload.get("output", response_payload or None)
        if output is not None and not isinstance(output, dict):
            output = {"response": output}
        default_message = (
            "Žiadosť sa nepodarilo odoslať. Skúste to prosím neskôr."
            if result_status == CapabilityStatus.FAILED
            else "Vaša žiadosť bola odoslaná personálu na spracovanie."
        )
        user_message = response_payload.get("user_message")
        if not isinstance(user_message, str):
            user_message = default_message
        error = response_payload.get("error")
        if error is not None and not isinstance(error, str):
            error = str(error)
        return CapabilityResult(
            name=capability_request.name,
            status=result_status,
            provider=self.provider_name,
            output=output,
            user_message=user_message,
            error=error,
        )

    def _failure(self, name: str, error: str) -> CapabilityResult:
        return CapabilityResult(
            name=name,
            status=CapabilityStatus.FAILED,
            provider=self.provider_name,
            user_message="Žiadosť sa nepodarilo odoslať. Skúste to prosím neskôr.",
            error=error,
        )


def valid_webhook_config(config: dict[str, Any]) -> bool:
    url = config.get("webhook_url")
    parsed = urlparse(url) if isinstance(url, str) else None
    timeout = config.get("timeout_seconds", MakeWebhookProvider.default_timeout_seconds)
    fields = config.get("payload_fields")
    response_format = config.get("response_format")
    valid_fields = fields is None or (
        isinstance(fields, dict)
        and bool(fields)
        and all(
            isinstance(output, str)
            and isinstance(source, str)
            and source in _PAYLOAD_SOURCES
            for output, source in fields.items()
        )
    )
    return bool(
        parsed
        and parsed.scheme in {"http", "https"}
        and parsed.netloc
        and isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and timeout > 0
        and valid_fields
        and response_format in (None, "availability_text", "acknowledgement")
    )


def _payload(
    tenant_context: TenantContext,
    request: CapabilityRequest,
    config: dict[str, Any],
) -> Any:
    if tenant_context.tenant_id != "penzion_grand":
        return {
            "tenant_id": tenant_context.tenant_id,
            "capability": request.name,
            "input": request.input,
            "metadata": request.metadata or {},
        }
    return [_penzion_grand_payload(tenant_context, request, config)]


def _penzion_grand_payload(
    tenant_context: TenantContext,
    request: CapabilityRequest,
    config: dict[str, Any],
) -> dict[str, Any]:
    values = request.input
    caller_phone = _phone_text(values.get("caller_number") or values.get("phone"))
    guest_phone = _phone_text(values.get("reservation_phone") or values.get("UserID"))
    sources = {
        "guest_name": values.get("reservation_name") or values.get("guest_name"),
        "booked_name": values.get("reservation_name") or values.get("booked_name"),
        "check_in": _date_text(values.get("check_in") or values.get("start_date")),
        "check_out": _date_text(values.get("check_out") or values.get("end_date")),
        "original_check_in": _date_text(
            values.get("original_check_in") or values.get("original_start_date")
        ),
        "original_check_out": _date_text(
            values.get("original_check_out") or values.get("original_end_date")
        ),
        "change": values.get("change") or values.get("modification"),
        "reason": values.get("reason") or values.get("notes") or "",
        "caller_number": caller_phone,
        "reservation_phone": guest_phone,
        "room_type_code": _room_type_code(tenant_context, values.get("room_type")),
        "room_count": values.get("room_count"),
        "room_count_text": str(values.get("room_count")),
    }
    fields = config.get("payload_fields")
    if isinstance(fields, dict):
        return {output: sources[source] for output, source in fields.items()}
    if request.name == "reservation.create_request":
        return {
            "guest_name": values.get("reservation_name") or values.get("guest_name"),
            "phone": caller_phone,
            "start_date": _date_text(values.get("check_in")),
            "end_date": _date_text(values.get("check_out")),
            "room_type": _room_type_code(tenant_context, values.get("room_type")),
            "room_count": values.get("room_count"),
            "userID": guest_phone,
        }
    if request.name == "reservation.change_request":
        return {
            "booked_name": values.get("reservation_name") or values.get("booked_name"),
            "original_start_date": _date_text(
                values.get("original_check_in") or values.get("original_start_date")
            ),
            "original_end_date": _date_text(
                values.get("original_check_out") or values.get("original_end_date")
            ),
            "modification": values.get("change") or values.get("modification"),
            "phone": caller_phone,
            "UserID": guest_phone,
        }
    if request.name == "reservation.cancel_request":
        return {
            "booked_name": values.get("reservation_name") or values.get("booked_name"),
            "original_start_date": _date_text(
                values.get("original_check_in") or values.get("original_start_date")
            ),
            "original_end_date": _date_text(
                values.get("original_check_out") or values.get("original_end_date")
            ),
            "notes": values.get("reason") or values.get("notes") or "",
            "UserID": guest_phone,
        }
    if request.name == "reservation.check_availability":
        return {
            "start_date": _date_text(values.get("check_in") or values.get("start_date")),
            "end_date": _date_text(values.get("check_out") or values.get("end_date")),
            "room_count": str(values.get("room_count")),
            "room_type": _room_type_code(tenant_context, values.get("room_type")),
            "caller_id": caller_phone,
        }
    if request.name == "reservation.check_existing_reservation":
        return {
            "guest_name": values.get("guest_name") or values.get("reservation_name"),
            "check_in": _date_text(values.get("check_in")),
            "check_out": _date_text(values.get("check_out")),
        }
    return values


def _date_text(value: Any) -> Any:
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).strftime("%d.%m.%Y")
        except ValueError:
            return value
    return value


def _phone_text(value: Any) -> Any:
    return "".join(value.split()) if isinstance(value, str) else value


def _availability_state(value: str) -> str:
    text = normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    if any(word in text for word in ("nedostup", "obsad", "unavailable", "not available")):
        return "unavailable"
    if any(word in text for word in ("voln", "dostup", "available", "free")):
        return "available"
    return "unknown"




def _room_type_code(tenant_context: TenantContext, value: Any) -> Any:
    if value is None or (isinstance(value, str) and value.isdigit()):
        return value
    capacities = {
        room.code: room.capacity for room in tenant_context.business_info.room_types
    }
    return str(capacities.get(value, value))
