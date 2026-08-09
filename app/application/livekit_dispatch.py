import logging
import os

from app.contracts.livekit import RuntimeToolDefinition


logger = logging.getLogger(__name__)


def resolve_voice_id(tenant) -> str:
    if tenant.voice.tts.voice_id:
        return tenant.voice.tts.voice_id
    if voice_id := os.getenv("ELEVENLABS_VOICE_ID", "").strip():
        return voice_id
    if voice_id := os.getenv("EVELENLABS_VOICE_ID", "").strip():
        logger.warning("EVELENLABS_VOICE_ID is deprecated; use ELEVENLABS_VOICE_ID")
        return voice_id
    raise ValueError("ElevenLabs voice ID is not configured")


def resolve_runtime_tools(tenant) -> tuple[RuntimeToolDefinition, ...]:
    tools = []
    for capability_name, capability in tenant.capabilities.items():
        if not capability.enabled:
            continue
        definition = _definition(capability_name, capability.config)
        if definition:
            tools.append(definition)
    return tuple(tools)


def _confirmation_note(config: dict) -> str:
    return (
        "Customer confirmation is required before invoking this tool."
        if config.get("confirmation_required")
        else "Customer confirmation is not required before invoking this tool."
    )


def _definition(capability: str, config: dict) -> RuntimeToolDefinition | None:
    common = {
        "enabled": True,
        "backend_capability": capability,
        "announcement": config.get("announcement"),
    }
    if capability == "calculator.calculate":
        return RuntimeToolDefinition(
            **common,
            public_name="calculate",
            description=(
                "Perform exactly one deterministic arithmetic operation. Use this tool instead "
                "of doing user-facing arithmetic yourself. For multi-step calculations, call it "
                "sequentially and use the previous result as an operand. percentage(a, b) means "
                "b percent of a."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide", "percentage"],
                    },
                    "operands": {
                        "type": "array",
                        "items": _text(128),
                        "minItems": 2,
                        "maxItems": 10,
                    },
                },
                "required": ["operation", "operands"],
                "additionalProperties": False,
            },
        )
    if capability == "reservation.check_availability":
        return RuntimeToolDefinition(
            **common,
            public_name="check_room_availability",
            description=(
                "Check room availability for every night of a requested stay. "
                f"{_confirmation_note(config)}"
            ),
            parameters=_object_schema(
                {
                    "check_in": _date(),
                    "check_out": _date(),
                    "room_type": _text(),
                    "room_count": {"type": "integer", "minimum": 1},
                }
            ),
        )
    if (
        capability == "reservation.create_request"
        and config.get("row_format") == "accommodation_request"
    ):
        return RuntimeToolDefinition(
            **common,
            public_name="submit_new_reservation_request",
            description=(
                "Submit a new accommodation request after availability and final guest confirmation. "
                f"{_confirmation_note(config)}"
            ),
            inject_caller_number=True,
            parameters=_object_schema(
                {
                    "check_in": _date(),
                    "check_out": _date(),
                    "reservation_name": _text(),
                    "reservation_phone": {
                        "type": ["string", "null"],
                        "minLength": 1,
                        "maxLength": 2_048,
                    },
                    "use_inbound_caller_number": {"type": "boolean"},
                    "room_type": _room_type(),
                    "room_count": {"type": "integer", "minimum": 1},
                    "confirmed": {"type": "boolean", "const": True},
                }
            ),
        )
    if capability == "reservation.create_request":
        return RuntimeToolDefinition(
            **common,
            public_name="create_reservation",
            description=(
                "Submit a reservation request for staff confirmation after collecting all required fields. "
                f"{_confirmation_note(config)}"
            ),
            inject_caller_number=True,
            argument_container="reservation_frame",
            parameters=_object_schema(
                {
                    "guest_name": _text(),
                    "date": _date(),
                    "time": {"type": "string", "minLength": 1, "maxLength": 32},
                    "party_size": {"type": "integer", "minimum": 1},
                    "phone": _text(),
                    "notes": {"type": ["string", "null"], "maxLength": 2_048},
                },
                required=("guest_name", "date", "time", "party_size", "phone"),
            ),
        )
    if capability == "reservation.change_request":
        return RuntimeToolDefinition(
            **common,
            public_name="submit_reservation_change_request",
            description=(
                "Submit any confirmed reservation change; availability fields are all-or-none. "
                f"{_confirmation_note(config)}"
            ),
            inject_caller_number=True,
            parameters=_object_schema(
                {
                    "original_check_in": _date(),
                    "original_check_out": _date(),
                    "reservation_name": _text(),
                    "reservation_phone": _text(),
                    "change": _text(4_096),
                    "confirmed": {"type": "boolean", "const": True},
                    "check_in": {"type": ["string", "null"], "format": "date"},
                    "check_out": {"type": ["string", "null"], "format": "date"},
                    "room_type": {"type": ["string", "null"], "enum": ["two_bed", "three_bed", "four_bed", None]},
                    "room_count": {"type": ["integer", "null"], "minimum": 1},
                },
                required=(
                    "original_check_in",
                    "original_check_out",
                    "reservation_name",
                    "reservation_phone",
                    "change",
                    "confirmed",
                ),
            ),
        )
    if capability == "reservation.cancel_request":
        return RuntimeToolDefinition(
            **common,
            public_name="submit_reservation_cancellation_request",
            description=(
                "Submit a reservation cancellation after final guest confirmation. "
                f"{_confirmation_note(config)}"
            ),
            inject_caller_number=True,
            parameters=_object_schema(
                {
                    "original_check_in": _date(),
                    "original_check_out": _date(),
                    "reservation_name": _text(),
                    "reservation_phone": _text(),
                    "confirmed": {"type": "boolean", "const": True},
                    "reason": {"type": "string", "maxLength": 4_096, "default": ""},
                },
                required=(
                    "original_check_in",
                    "original_check_out",
                    "reservation_name",
                    "reservation_phone",
                    "confirmed",
                ),
            ),
        )
    return None


def _object_schema(properties: dict, *, required: tuple[str, ...] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or properties),
        "additionalProperties": False,
    }


def _text(max_length: int = 512) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


def _date() -> dict:
    return {"type": "string", "format": "date"}


def _room_type() -> dict:
    return {"type": "string", "enum": ["two_bed", "three_bed", "four_bed"]}
