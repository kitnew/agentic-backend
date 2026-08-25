import json
import re
from datetime import date, datetime
from hashlib import sha256
from typing import Any, Protocol, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import jsonata  # type: ignore[import-untyped]
from contracts import (
    CANONICAL_FIELD_NORMALIZERS,
    CANONICAL_FIELDS,
    CapabilityInputConstraint,
    ExecutionPlan,
    ExpressionNode,
    GoogleSheetsAppendExecution,
    GoogleSheetsAppendValuesPlan,
    GoogleSheetsIdempotency,
    HttpExecution,
    HttpRequestPlanV1,
    HttpRequestResult,
    ManagedWebhookResponseConfig,
    RuntimeCapabilityBinding,
    RuntimeCapabilityDefinition,
    RuntimeCapabilityInputConstraint,
    RuntimeGoogleSheetsExecution,
    RuntimeHttpExecution,
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

from backend_core.runtime.capabilities.execution import ExecutionOutcome
from backend_core.runtime.capabilities.mapping import evaluate_query, evaluate_template

MAX_MAPPING_INPUT_BYTES = 64_000
MAX_MAPPING_OUTPUT_BYTES = 64_000
MAPPING_LANGUAGE = "jsonata"
MAPPING_CONTRACT_VERSION = 1
MAPPING_ENGINE = "jsonata-python"
MAPPING_ENGINE_VERSION = "0.7.0"


CanonicalCapabilityResult = dict[str, object] | str | None


class CapabilityValidationError(ValueError):
    def __init__(self, code: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


def validate_bindings(schema: dict[str, Any], bindings: dict[str, str]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise CapabilityValidationError("invalid_json_schema", error.message) from error
    _walk_refs(schema)
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise CapabilityValidationError(
            "invalid_json_schema", "Input schema must be a closed object"
        )
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise CapabilityValidationError(
            "invalid_json_schema", "Input schema properties are required"
        )
    mapped: set[str] = set()
    for name, target in bindings.items():
        if name not in properties:
            raise CapabilityValidationError(
                "invalid_binding",
                "Binding input is not in input_schema",
                f"bindings.{name}",
            )
        if not isinstance(target, str) or not re.fullmatch(
            r"(?:[a-z][a-z0-9_]*\.)*[a-z][a-z0-9_]*", target
        ):
            raise CapabilityValidationError(
                "invalid_binding", "Binding target is invalid", f"bindings.{name}"
            )
        if target.startswith("custom."):
            continue
        if target not in CANONICAL_FIELDS:
            raise CapabilityValidationError(
                "unknown_domain_field",
                "Unknown canonical domain field",
                f"bindings.{name}",
            )
        if target in mapped:
            raise CapabilityValidationError(
                "invalid_binding", "Binding target is duplicated", f"bindings.{name}"
            )
        expected = CANONICAL_FIELDS[target]
        actual = (
            properties[name].get("type") if isinstance(properties[name], dict) else None
        )
        if actual is not None and actual != expected:
            raise CapabilityValidationError(
                "binding_type_mismatch",
                "Input type is incompatible with domain field",
                f"bindings.{name}",
            )
        mapped.add(target)


def validate_input_constraints(
    schema: dict[str, Any],
    bindings: dict[str, str],
    constraints: list[CapabilityInputConstraint],
) -> None:
    properties = schema["properties"]
    required = set(schema.get("required", []))
    bound_inputs = {target: source for source, target in bindings.items()}
    for index, constraint in enumerate(constraints):
        if constraint.start == constraint.end:
            raise CapabilityValidationError(
                "invalid_input_constraint",
                "Date range start and end must be different",
                f"input_constraints.{index}",
        )
        for field_name in (constraint.start, constraint.end):
            if field_name not in CANONICAL_FIELDS:
                raise CapabilityValidationError(
                    "invalid_input_constraint",
                    f"Constraint field must be canonical: {field_name}",
                    f"input_constraints.{index}",
                )
            source = bound_inputs.get(field_name)
            if source is None:
                raise CapabilityValidationError(
                    "invalid_input_constraint",
                    f"Constraint field is not bound: {field_name}",
                    f"input_constraints.{index}",
                )
            source_schema = properties.get(source)
            if not isinstance(source_schema, dict) or (
                source_schema.get("type") != "string"
                or source_schema.get("format") != "date"
            ):
                raise CapabilityValidationError(
                    "invalid_input_constraint",
                    f"Constraint field must use a string date schema: {source}",
                    f"input_constraints.{index}",
                )
            if source not in required:
                raise CapabilityValidationError(
                    "invalid_input_constraint",
                    f"Constraint field must be required by schema: {source}",
                    f"input_constraints.{index}",
                )


def _normalize_canonical_value(target: str, value: Any) -> Any:
    normalizer = CANONICAL_FIELD_NORMALIZERS.get(target)
    if normalizer == "trim":
        return value.strip() if isinstance(value, str) else value
    if normalizer == "e164" and value is not None:
        if not isinstance(value, str):
            raise CapabilityValidationError(
                "invalid_canonical_field", "Phone number must be a string", target
            )
        compact = re.sub(r"[\s()-]", "", value)
        if compact.startswith("00"):
            compact = f"+{compact[2:]}"
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", compact):
            raise CapabilityValidationError(
                "invalid_canonical_field",
                "Phone number must be international E.164",
                target,
            )
        return compact
    return value


def _tool_name(semantic_key: str) -> str:
    tool_name = semantic_key.replace(".", "_")
    if len(tool_name) <= 64:
        return tool_name
    return f"{tool_name[:55]}_{sha256(semantic_key.encode()).hexdigest()[:8]}"


def _validate_mapping_expressions(profile: TenantCapabilityProfile) -> None:
    def visit(value: object) -> None:
        if isinstance(value, ExpressionNode):
            jsonata.Jsonata(value.expr)
            return
        if isinstance(value, dict):
            if set(value) == {"$expr"}:
                jsonata.Jsonata(value["$expr"])
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    execution = profile.execution
    if isinstance(execution, (HttpExecution, RuntimeHttpExecution)):
        visit(execution.path)
        visit(execution.query)
        visit(execution.request.mapping)
        visit(execution.response.mapping)
        if execution.result_schema is not None:
            try:
                Draft202012Validator.check_schema(execution.result_schema)
            except SchemaError as error:
                raise CapabilityValidationError(
                    "invalid_result_schema", error.message, "execution.result_schema"
                ) from error
    else:
        jsonata.Jsonata(execution.request_mapping)


def resolve_capability(
    semantic_key: str, profile: TenantCapabilityProfile
) -> RuntimeCapabilityDefinition:
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", semantic_key):
        raise CapabilityValidationError(
            "invalid_semantic_key",
            "Capability semantic key is invalid",
            "semantic_key",
        )
    if isinstance(profile.semantic_version, bool) or profile.semantic_version < 1:
        raise CapabilityValidationError(
            "invalid_semantic_version",
            "Capability semantic version is invalid",
            "semantic_version",
        )
    if profile.business_policy.requires_availability_proof:
        raise CapabilityValidationError(
            "unsupported_business_policy",
            "Availability proof is not implemented",
            "business_policy.requires_availability_proof",
        )
    validate_bindings(profile.agent_input_schema, profile.bindings)
    validate_input_constraints(
        profile.agent_input_schema,
        profile.bindings,
        profile.input_constraints,
    )
    try:
        _validate_mapping_expressions(profile)
    except CapabilityValidationError:
        raise
    except Exception as error:
        raise CapabilityValidationError(
            "invalid_mapping_expression",
            "Mapping expression is invalid",
            "execution",
        ) from error
    return RuntimeCapabilityDefinition(
        semantic_key=semantic_key,
        semantic_version=profile.semantic_version,
        tool_name=_tool_name(semantic_key),
        description=profile.description,
        announcement=profile.announcement,
        input_schema=json.loads(json.dumps(profile.agent_input_schema)),
        requires_confirmation=profile.business_policy.requires_final_confirmation,
    )


class MappingEngine(Protocol):
    def evaluate(self, expression: str, data: dict[str, Any]) -> dict[str, Any]: ...


class JsonataMappingEngine:
    def evaluate(self, expression: str, data: dict[str, Any]) -> object:
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
        return json.loads(output)


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
            if key.startswith("x-"):
                raise CapabilityValidationError(
                    "unsupported_schema_extension",
                    "Unsupported JSON Schema extension",
                    child_path,
                )
            _walk_refs(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_refs(item, f"{path}.{index}")


def validate_agent_input(schema: dict[str, Any], value: dict[str, Any]) -> None:
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path)
        raise CapabilityValidationError(
            "invalid_agent_input", error.message, path
        ) from error


def validate_response_config(response: ManagedWebhookResponseConfig) -> None:
    schema = response.output_schema
    try:
        encoded = response.model_dump_json()
        if len(encoded.encode()) > MAX_MAPPING_INPUT_BYTES:
            raise CapabilityValidationError(
                "response_config_too_large", "Response configuration is too large"
            )
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise CapabilityValidationError(
            "invalid_output_schema", error.message, "execution.response.output_schema"
        ) from error
    if not isinstance(schema.get("type"), str) or (
        schema.get("type") == "object"
        and schema.get("additionalProperties") is not False
    ):
        raise CapabilityValidationError(
            "invalid_output_schema",
            "Output schema must be a closed object",
            "execution.response.output_schema",
        )
    if _contains_ref(schema):
        raise CapabilityValidationError(
            "invalid_output_schema",
            "Output schema references are not supported",
            "execution.response.output_schema",
        )
    if response.mapping is not None:
        try:
            jsonata.Jsonata(response.mapping)
        except Exception as error:
            raise CapabilityValidationError(
                "invalid_response_mapping",
                "Response mapping is invalid",
                "execution.response.mapping",
            ) from error
    if response.success_output is not None:
        try:
            Draft202012Validator(schema).validate(response.success_output)
        except ValidationError as error:
            raise CapabilityValidationError(
                "invalid_response_output",
                error.message,
                "execution.response.success_output",
            ) from error


def _contains_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item) for item in value)
    return False


def _set_nested(target: dict[str, Any], dotted: str, value: Any) -> None:
    current = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def normalize_input(
    value: dict[str, Any], bindings: dict[str, str] | None = None
) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "guest": {"name": None, "phone": None, "email": None},
        "stay": {"check_in": None, "check_out": None},
        "allocation": {"room_type": None, "room_count": None},
        "notes": None,
        "custom": {},
    }
    for name, item in value.items():
        target = (bindings or {}).get(name, f"custom.{name}")
        _set_nested(normalized, target, _normalize_canonical_value(target, item))
    return normalized


def enforce_input_constraints(
    value: dict[str, Any],
    timezone: str,
    constraints: list[RuntimeCapabilityInputConstraint],
) -> None:
    def get_nested(path: str) -> Any:
        current: Any = value
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    for index, constraint in enumerate(constraints):
        try:
            start = date.fromisoformat(get_nested(constraint.start))
            end = date.fromisoformat(get_nested(constraint.end))
        except (TypeError, ValueError) as error:
            raise CapabilityValidationError(
                "input_constraint_rejected",
                "Date range values must be valid ISO dates",
                f"input_constraints.{index}",
            ) from error
        if end <= start:
            raise CapabilityValidationError(
                "input_constraint_rejected",
                "Check-out must be after check-in",
                constraint.end,
            )
        if constraint.start_not_in_past and start < datetime.now(ZoneInfo(timezone)).date():
            raise CapabilityValidationError(
                "input_constraint_rejected",
                "Check-in cannot be in the past",
                constraint.start,
            )


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
    profile: TenantCapabilityProfile | RuntimeCapabilityBinding,
    canonical_input: dict[str, Any],
    *,
    operation_id: UUID,
    call_id: UUID,
    tool_call_id: str,
    integration_id: UUID,
    semantic_key: str,
    caller_phone: str = "",
    mapping_engine: MappingEngine | None = None,
) -> GoogleSheetsAppendValuesPlan | HttpRequestPlanV1:
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
    if isinstance(execution, (HttpExecution, RuntimeHttpExecution)):
        payload = None
        if execution.request.codec != "none":
            if execution.request.mapping is None:
                raise CapabilityValidationError(
                    "invalid_mapping_output",
                    "HTTP request mapping is required",
                    "execution.request.mapping",
                )
            payload = evaluate_template(execution.request.mapping, source)
            if execution.request.codec == "text" and not isinstance(payload, str):
                raise CapabilityValidationError(
                    "invalid_mapping_output",
                    "Text request mapping must evaluate to a string",
                    "execution.request.mapping",
                )
        path = execution.path
        if not isinstance(path, str) and path is not None:
            path = evaluate_template(path, source)
            if not isinstance(path, str) or "://" in path or "#" in path:
                raise CapabilityValidationError(
                    "invalid_path", "HTTP path must be relative", "execution.path"
                )
        query = evaluate_query(execution.query, source)
        return HttpRequestPlanV1(
            integration_id=integration_id,
            operation_id=operation_id,
            capability={
                "semantic_key": semantic_key,
                "semantic_version": profile.semantic_version,
            },
            method=execution.method,
            path=path,
            query=query,
            headers=execution.headers,
            request=execution.request,
            response=execution.response,
            payload=payload,
            timeout_seconds=execution.timeout_seconds,
            success_statuses=execution.success_statuses,
            result_schema=execution.result_schema,
        )
    mapped = (mapping_engine or JsonataMappingEngine()).evaluate(
        execution.request_mapping, source
    )
    if not isinstance(mapped, dict):
        raise CapabilityValidationError(
            "invalid_mapping_output", "Mapping output must be an object"
        )
    rows = mapped_rows(mapped)
    if not isinstance(
        execution, (GoogleSheetsAppendExecution, RuntimeGoogleSheetsExecution)
    ):
        raise CapabilityValidationError(
            "configuration_invalid", "Capability execution is unavailable"
        )
    index = (
        execution.idempotency.operation_id_column_index
        if isinstance(execution, GoogleSheetsAppendExecution)
        else execution.operation_id_column_index
    )
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
        integration_id=integration_id,
        spreadsheet_id=execution.spreadsheet_id,
        sheet_name=execution.sheet_name,
        append_range=execution.append_range,
        value_input_option=execution.value_input_option,
        rows=rows,
        idempotency=GoogleSheetsIdempotency(
            operation_id=operation_id,
            lookup_range=(
                execution.idempotency.lookup_range
                if isinstance(execution, GoogleSheetsAppendExecution)
                else execution.lookup_range
            ),
            operation_id_column_index=index,
        ),
    )


def validate_result_for_plan(
    execution_plan: dict[str, object], result: TechnicalResult
) -> ExecutionPlan:
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
    if isinstance(plan, HttpRequestPlanV1) and plan.result_schema is not None:
        if not isinstance(result, HttpRequestResult):
            raise CapabilityValidationError(
                "result_plan_mismatch", "Worker result does not match execution plan"
            )
        try:
            Draft202012Validator(plan.result_schema).validate(result.data)
        except (SchemaError, ValidationError) as error:
            raise CapabilityValidationError(
                "invalid_semantic_result", "Result violates result_schema"
            ) from error
    return plan


def semantic_result(outcome: ExecutionOutcome) -> CanonicalCapabilityResult:
    if not isinstance(outcome.data, (dict, str, type(None))):
        raise CapabilityValidationError(
            "invalid_semantic_result",
            "Capability result must be an object, string, or null",
        )
    return cast(CanonicalCapabilityResult, outcome.data)
