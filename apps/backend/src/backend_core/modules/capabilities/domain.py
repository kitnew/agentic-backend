import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import jsonata  # type: ignore[import-untyped]
from contracts import (
    ExecutionPlan,
    GoogleSheetsAppendValuesPlan,
    GoogleSheetsIdempotency,
    ManagedWebhookCapability,
    ManagedWebhookExecution,
    ManagedWebhookPostJsonPlan,
    ReservationRequestSubmitted,
    RuntimeCapabilityDefinition,
    TechnicalResult,
    TenantCapabilityProfile,
)
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    SchemaError,
    ValidationError,
)
from pydantic import TypeAdapter

from backend_core.modules.capabilities.execution import ExecutionOutcome

CANONICAL_FIELDS = {
    "guest.name": "string",
    "guest.phone": "string",
    "guest.email": "string",
    "stay.check_in": "string",
    "stay.check_out": "string",
    "allocation.room_type": "integer",
    "allocation.room_count": "integer",
    "notes": "string",
}
SEMANTIC_REQUIRED_FIELDS = frozenset({"guest.name", "stay.check_in", "stay.check_out"})
SEMANTIC_KEY = "reservation.submit_request"
SEMANTIC_VERSION = 1
TOOL_NAME = "reservation_submit_request"
MAX_MAPPING_INPUT_BYTES = 64_000
MAX_MAPPING_OUTPUT_BYTES = 64_000
MAPPING_LANGUAGE = "jsonata"
MAPPING_CONTRACT_VERSION = 1
MAPPING_ENGINE = "jsonata-python"
MAPPING_ENGINE_VERSION = "0.7.0"


@dataclass(frozen=True)
class CapabilityDefinition:
    semantic_key: str
    semantic_version: int
    kind: str
    canonical_fields: dict[str, str]
    required_fields: frozenset[str]
    tool_name: str


REGISTRY = {
    (SEMANTIC_KEY, SEMANTIC_VERSION): CapabilityDefinition(
        semantic_key=SEMANTIC_KEY,
        semantic_version=SEMANTIC_VERSION,
        kind="command",
        canonical_fields=CANONICAL_FIELDS,
        required_fields=SEMANTIC_REQUIRED_FIELDS,
        tool_name=TOOL_NAME,
    )
}


SemanticResultMapper = Callable[[ExecutionOutcome], ReservationRequestSubmitted]


class CapabilityValidationError(ValueError):
    def __init__(self, code: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


class MappingEngine(Protocol):
    def evaluate(self, expression: str, data: dict[str, Any]) -> dict[str, Any]: ...


class JsonataMappingEngine:
    def evaluate(self, expression: str, data: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > MAX_MAPPING_INPUT_BYTES:
            raise CapabilityValidationError(
                "mapping_input_too_large", "Mapping input is too large"
            )
        try:
            result = jsonata.Jsonata(expression).evaluate(json.loads(encoded))
            output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except Exception as error:
            raise CapabilityValidationError(
                "mapping_failed", "JSONata mapping failed"
            ) from error
        if len(output.encode()) > MAX_MAPPING_OUTPUT_BYTES:
            raise CapabilityValidationError(
                "mapping_output_too_large", "Mapping output is too large"
            )
        decoded = json.loads(output)
        if not isinstance(decoded, dict):
            raise CapabilityValidationError(
                "invalid_mapping_output", "Mapping output must be an object"
            )
        return decoded


def definition(semantic_key: str, semantic_version: int) -> CapabilityDefinition:
    found = REGISTRY.get((semantic_key, semantic_version))
    if found is None:
        raise CapabilityValidationError(
            "unsupported_capability_version",
            "Capability semantic key or version is unsupported",
        )
    return found


def _walk_refs(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "$ref" and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise CapabilityValidationError(
                    "remote_ref_not_allowed",
                    "Only local JSON Schema references are allowed",
                    child_path,
                )
            if key.startswith("x-") and key not in {
                "x-canonical-field",
                "x-custom-field",
            }:
                raise CapabilityValidationError(
                    "unsupported_schema_extension",
                    "Unsupported JSON Schema extension",
                    child_path,
                )
            _walk_refs(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_refs(item, f"{path}.{index}")


def _resolve_local_schema(
    schema: dict[str, Any], property_schema: dict[str, Any]
) -> dict[str, Any]:
    ref = property_schema.get("$ref")
    if ref is None:
        return property_schema
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        raise CapabilityValidationError(
            "unsupported_local_ref", "Only local $defs references are supported"
        )
    target: Any = schema
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            raise CapabilityValidationError(
                "invalid_local_ref", "Local JSON Schema reference was not found"
            )
        target = target[part]
    if not isinstance(target, dict):
        raise CapabilityValidationError(
            "invalid_local_ref", "Local JSON Schema reference must target a schema"
        )
    return {
        **target,
        **{key: value for key, value in property_schema.items() if key != "$ref"},
    }


def validate_agent_schema(
    schema: dict[str, Any], capability: CapabilityDefinition
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise CapabilityValidationError("invalid_json_schema", error.message) from error
    _walk_refs(schema)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise CapabilityValidationError(
            "invalid_json_schema_draft", "Draft 2020-12 is required", "$schema"
        )
    if schema.get("type") != "object":
        raise CapabilityValidationError(
            "invalid_schema_root", "Schema root type must be object", "type"
        )
    if schema.get("additionalProperties") is not False:
        raise CapabilityValidationError(
            "additional_properties_not_forbidden",
            "additionalProperties must be false",
            "additionalProperties",
        )
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise CapabilityValidationError(
            "invalid_schema_root", "properties and required are required"
        )
    mapped: set[str] = set()
    for name, raw_property in properties.items():
        if not isinstance(raw_property, dict):
            raise CapabilityValidationError(
                "invalid_property_schema",
                "Property schema must be an object",
                f"properties.{name}",
            )
        canonical = raw_property.get("x-canonical-field")
        custom = raw_property.get("x-custom-field")
        if (canonical is None) == (custom is None):
            raise CapabilityValidationError(
                "invalid_field_mapping",
                "Exactly one canonical or custom mapping is required",
                f"properties.{name}",
            )
        effective = _resolve_local_schema(schema, raw_property)
        if canonical is not None:
            if canonical not in capability.canonical_fields:
                raise CapabilityValidationError(
                    "unknown_canonical_field",
                    "Unknown canonical field",
                    f"properties.{name}",
                )
            if canonical in mapped:
                raise CapabilityValidationError(
                    "duplicate_canonical_field",
                    "Canonical field is mapped more than once",
                    f"properties.{name}",
                )
            if effective.get("type") != capability.canonical_fields[canonical]:
                raise CapabilityValidationError(
                    "canonical_type_mismatch",
                    "Property type is incompatible with canonical field",
                    f"properties.{name}.type",
                )
            mapped.add(canonical)
        elif not isinstance(custom, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", custom
        ):
            raise CapabilityValidationError(
                "invalid_custom_field",
                "Custom field name is invalid",
                f"properties.{name}",
            )
    missing = capability.required_fields - mapped
    if missing:
        raise CapabilityValidationError(
            "missing_semantic_field",
            f"Missing semantic fields: {', '.join(sorted(missing))}",
        )
    mapped_properties = {
        name
        for name, value in properties.items()
        if isinstance(value, dict)
        and value.get("x-canonical-field") in capability.required_fields
    }
    if not mapped_properties <= set(required):
        raise CapabilityValidationError(
            "semantic_field_not_required", "Semantic fields must be required"
        )


def validate_agent_input(schema: dict[str, Any], value: dict[str, Any]) -> None:
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path)
        raise CapabilityValidationError(
            "invalid_agent_input", error.message, path
        ) from error


def _set_nested(target: dict[str, Any], dotted: str, value: Any) -> None:
    current = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def normalize_input(schema: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "guest": {"name": None, "phone": None, "email": None},
        "stay": {"check_in": None, "check_out": None},
        "allocation": {"room_type": None, "room_count": None},
        "notes": None,
        "custom": {},
    }
    properties = schema["properties"]
    for name, item in value.items():
        property_schema = properties[name]
        canonical = property_schema.get("x-canonical-field")
        if canonical:
            _set_nested(normalized, canonical, item)
        else:
            normalized["custom"][property_schema["x-custom-field"]] = item
    return normalized


def validate_business_input(
    value: dict[str, Any],
    timezone: str,
    *,
    today: date | None = None,
    enforce_not_past: bool = True,
) -> dict[str, Any]:
    name = value["guest"]["name"]
    if not isinstance(name, str) or not name.strip():
        raise CapabilityValidationError(
            "business_policy_rejected", "Guest name is required", "guest.name"
        )
    value["guest"]["name"] = name.strip()
    try:
        check_in = date.fromisoformat(value["stay"]["check_in"])
        check_out = date.fromisoformat(value["stay"]["check_out"])
    except (TypeError, ValueError) as error:
        raise CapabilityValidationError(
            "business_policy_rejected", "Stay dates must be valid ISO dates", "stay"
        ) from error
    local_today = today or datetime.now(ZoneInfo(timezone)).date()
    if enforce_not_past and check_in < local_today:
        raise CapabilityValidationError(
            "business_policy_rejected",
            "Check-in cannot be in the past",
            "stay.check_in",
        )
    if check_out <= check_in:
        raise CapabilityValidationError(
            "business_policy_rejected",
            "Check-out must be after check-in",
            "stay.check_out",
        )
    phone = value["guest"].get("phone")
    if phone is not None:
        if not isinstance(phone, str):
            raise CapabilityValidationError(
                "business_policy_rejected",
                "Phone number must be a string",
                "guest.phone",
            )
        compact = re.sub(r"[\s()-]", "", phone)
        if compact.startswith("00"):
            compact = f"+{compact[2:]}"
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", compact):
            raise CapabilityValidationError(
                "business_policy_rejected",
                "Phone number must be international E.164",
                "guest.phone",
            )
        value["guest"]["phone"] = compact
    email = value["guest"].get("email")
    if email is not None and (not isinstance(email, str) or not email.strip()):
        raise CapabilityValidationError(
            "business_policy_rejected",
            "Email must be a non-empty string",
            "guest.email",
        )
    if isinstance(email, str):
        value["guest"]["email"] = email.strip()
    room_type = value["allocation"].get("room_type")
    if room_type is not None and room_type not in {2, 3, 4}:
        raise CapabilityValidationError(
            "business_policy_rejected",
            "Room type must be 2, 3 or 4",
            "allocation.room_type",
        )
    room_count = value["allocation"].get("room_count")
    if room_count is not None and (type(room_count) is not int or room_count < 1):
        raise CapabilityValidationError(
            "business_policy_rejected",
            "Room count must be an integer >= 1",
            "allocation.room_count",
        )
    return value


def mapped_rows(output: dict[str, Any]) -> list[list[str | int | float | bool | None]]:
    rows = output.get("rows")
    if not isinstance(rows, list) or len(rows) != 1:
        raise CapabilityValidationError(
            "invalid_mapping_output",
            "Mapping output must contain exactly one row",
            "rows",
        )
    for row in rows:
        if not isinstance(row, list) or not row:
            raise CapabilityValidationError(
                "invalid_mapping_output", "Each row must be a non-empty array", "rows"
            )
        if any(type(cell) not in {str, int, float, bool, type(None)} for cell in row):
            raise CapabilityValidationError(
                "invalid_mapping_output",
                "Rows may contain only JSON scalar values",
                "rows",
            )
    return rows


def compile_plan(
    profile: TenantCapabilityProfile,
    canonical_input: dict[str, Any],
    *,
    operation_id: UUID,
    call_id: UUID,
    tool_call_id: str,
    credential_ref: str,
    caller_phone: str = "",
    mapping_engine: MappingEngine | None = None,
) -> GoogleSheetsAppendValuesPlan | ManagedWebhookPostJsonPlan:
    execution = profile.execution
    source = {
        "business": canonical_input,
        "metadata": {
            "operation_id": str(operation_id),
            "invocation_id": str(operation_id),
            "source": "voice_agent",
            "caller_phone": caller_phone,
            "call_id": str(call_id),
            "tool_call_id": tool_call_id,
        },
    }
    mapped = (mapping_engine or JsonataMappingEngine()).evaluate(
        execution.request_mapping,
        source,
    )
    if isinstance(execution, ManagedWebhookExecution):
        reserved = {"contract_version", "operation_id", "capability"}
        if reserved.intersection(mapped):
            raise CapabilityValidationError(
                "mapping_reserved_field",
                "Webhook mapping cannot define authoritative envelope fields",
                "execution.request_mapping",
            )
        return ManagedWebhookPostJsonPlan(
            plan_type=execution.plan_type,
            connection_ref=credential_ref,
            operation_id=operation_id,
            capability=ManagedWebhookCapability(
                semantic_key=SEMANTIC_KEY,
                semantic_version=profile.semantic_version,
            ),
            payload=mapped,
            timeout_seconds=execution.timeout_seconds,
        )
    rows = mapped_rows(mapped)
    index = execution.idempotency.operation_id_column_index
    if any(len(row) <= index or row[index] != str(operation_id) for row in rows):
        raise CapabilityValidationError(
            "operation_id_not_mapped",
            "Mapping must place metadata.operation_id in the idempotency column",
            "execution.request_mapping",
        )
    return GoogleSheetsAppendValuesPlan(
        plan_type=execution.plan_type,
        mapping_language=execution.mapping_language,
        mapping_contract_version=execution.mapping_contract_version,
        mapping_engine=execution.mapping_engine,
        mapping_engine_version=execution.mapping_engine_version,
        credential_ref=credential_ref,
        spreadsheet_id=execution.spreadsheet_id,
        sheet_name=execution.sheet_name,
        append_range=execution.append_range,
        value_input_option=execution.value_input_option,
        rows=rows,
        idempotency=GoogleSheetsIdempotency(
            operation_id=operation_id,
            lookup_range=execution.idempotency.lookup_range,
            operation_id_column_index=index,
        ),
    )


def _reservation_result(outcome: ExecutionOutcome) -> ReservationRequestSubmitted:
    return ReservationRequestSubmitted(
        request_reference=outcome.reference,
        deduplicated=outcome.deduplicated,
    )


SEMANTIC_RESULT_MAPPERS: dict[tuple[str, int], SemanticResultMapper] = {
    (SEMANTIC_KEY, SEMANTIC_VERSION): _reservation_result,
}


def validate_result_for_plan(
    execution_plan: dict[str, object], result: TechnicalResult
) -> None:
    try:
        plan: ExecutionPlan = TypeAdapter(ExecutionPlan).validate_python(execution_plan)
    except Exception as error:
        raise CapabilityValidationError(
            "execution_plan_invalid", "Invocation execution plan is invalid"
        ) from error
    if result.result_type != plan.plan_type:
        raise CapabilityValidationError(
            "result_plan_mismatch", "Worker result does not match execution plan"
        )


def semantic_result(
    semantic_key: str, semantic_version: int, outcome: ExecutionOutcome
) -> ReservationRequestSubmitted:
    mapper = SEMANTIC_RESULT_MAPPERS.get((semantic_key, semantic_version))
    if mapper is None:
        raise CapabilityValidationError(
            "unsupported_capability_version",
            "Capability semantic key or version is unsupported",
        )
    return mapper(outcome)


def runtime_definition(
    semantic_key: str,
    profile: TenantCapabilityProfile,
) -> RuntimeCapabilityDefinition:
    capability = definition(semantic_key, profile.semantic_version)
    schema = json.loads(json.dumps(profile.agent_input_schema))
    for property_schema in schema.get("properties", {}).values():
        if isinstance(property_schema, dict):
            property_schema.pop("x-canonical-field", None)
            property_schema.pop("x-custom-field", None)
    return RuntimeCapabilityDefinition(
        semantic_key=semantic_key,
        semantic_version=profile.semantic_version,
        tool_name=capability.tool_name,
        description=profile.description,
        announcement=profile.announcement,
        input_schema=schema,
        requires_confirmation=profile.business_policy.requires_final_confirmation,
    )
