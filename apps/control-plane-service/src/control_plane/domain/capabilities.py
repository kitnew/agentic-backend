from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

import jsonata  # type: ignore[import-untyped]
from contracts import CANONICAL_FIELD_NORMALIZERS, CANONICAL_FIELDS
from contracts.http_operation import ExpressionNode, HttpOperation, MappingTemplate
from contracts.tenant_components import (
    CapabilityBusinessPolicy,
    CapabilityInputConstraint,
)
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)
from pydantic_core import core_schema

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentKind,
    ScopeType,
)
from control_plane.domain.components.errors import InvalidComponentValue


@dataclass(frozen=True, slots=True)
class IntegrationConnectionRef:
    value: UUID

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source: object, _handler: object
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.uuid_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda ref: str(ref.value)
            ),
        )


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HttpCapabilityExecution(_CapabilityModel):
    integration_connection_ref: IntegrationConnectionRef
    method: str
    path: str | ExpressionNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: Any = Field(default_factory=lambda: {"codec": "none"})
    response: Any = Field(default_factory=lambda: {"codec": "none"})
    timeout_seconds: float
    success_statuses: list[int] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def operation_is_valid(self) -> HttpCapabilityExecution:
        HttpOperation.model_validate(
            self.model_dump(mode="python", exclude={"integration_connection_ref"})
            | {"connection": "integration"}
        )
        return self


class TenantCapabilityProfile(_CapabilityModel):
    enabled: StrictBool
    description: str = Field(min_length=1, max_length=1000)
    announcement: str | dict[str, str] = Field(min_length=1)
    agent_input_schema: dict[str, Any]
    bindings: dict[str, str] = Field(default_factory=dict)
    input_constraints: list[CapabilityInputConstraint] = Field(default_factory=list)
    business_policy: CapabilityBusinessPolicy = Field(
        default_factory=CapabilityBusinessPolicy
    )
    execution: HttpCapabilityExecution
    result_schema: dict[str, object] | None = None


class TenantCapabilitiesConfig(_CapabilityModel):
    capabilities: dict[str, StrictBool | TenantCapabilityProfile] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def profiles_are_valid(self) -> TenantCapabilitiesConfig:
        tools: set[str] = set()
        for key, profile in self.capabilities.items():
            if isinstance(profile, bool):
                continue
            validate_capability(key, profile)
            if profile.enabled:
                tool = derive_tool_name(key)
                if tool in tools:
                    raise ValueError("duplicate derived tool name")
                tools.add(tool)
        return self


def derive_tool_name(semantic_key: str) -> str:
    tool_name = semantic_key.replace(".", "_")
    return (
        tool_name
        if len(tool_name) <= 64
        else f"{tool_name[:55]}_{sha256(semantic_key.encode()).hexdigest()[:8]}"
    )


def validate_capability(semantic_key: str, profile: TenantCapabilityProfile) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", semantic_key):
        raise InvalidComponentValue("Capability semantic key is invalid")
    if profile.business_policy.requires_availability_proof:
        raise InvalidComponentValue("Availability proof is not implemented")
    _validate_bindings(profile.agent_input_schema, profile.bindings)
    _validate_constraints(
        profile.agent_input_schema, profile.bindings, profile.input_constraints
    )
    _validate_expression(profile.execution.path)
    _validate_expression(profile.execution.query)
    _validate_expression(profile.execution.request)
    _validate_expression(profile.execution.response)
    if profile.result_schema is not None:
        try:
            Draft202012Validator.check_schema(profile.result_schema)
        except SchemaError as error:
            raise InvalidComponentValue(
                f"invalid result schema: {error.message}"
            ) from error


def _validate_bindings(schema: dict[str, Any], bindings: dict[str, str]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise InvalidComponentValue(f"invalid JSON Schema: {error.message}") from error
    _walk_schema(schema)
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise InvalidComponentValue("Input schema must be a closed object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise InvalidComponentValue("Input schema properties are required")
    targets: set[str] = set()
    for source, target in bindings.items():
        if source not in properties or not re.fullmatch(
            r"(?:[a-z][a-z0-9_]*\.)*[a-z][a-z0-9_]*", target
        ):
            raise InvalidComponentValue("invalid capability binding")
        if target.startswith("custom."):
            continue
        if target not in CANONICAL_FIELDS or target in targets:
            raise InvalidComponentValue("unknown or duplicate canonical binding")
        actual = (
            properties[source].get("type")
            if isinstance(properties[source], dict)
            else None
        )
        if actual is not None and actual != CANONICAL_FIELDS[target]:
            raise InvalidComponentValue(
                "binding type is incompatible with canonical target"
            )
        targets.add(target)


def _validate_constraints(
    schema: dict[str, Any],
    bindings: dict[str, str],
    constraints: list[CapabilityInputConstraint],
) -> None:
    properties, required = schema["properties"], set(schema.get("required", []))
    bound = {target: source for source, target in bindings.items()}
    for constraint in constraints:
        if constraint.start == constraint.end:
            raise InvalidComponentValue("date range start and end must differ")
        for target in (constraint.start, constraint.end):
            source = bound.get(target)
            field = properties.get(source) if source else None
            if (
                target not in CANONICAL_FIELDS
                or source is None
                or source not in required
                or not isinstance(field, dict)
                or field.get("type") != "string"
                or field.get("format") != "date"
            ):
                raise InvalidComponentValue(
                    "date range fields must be required bound canonical dates"
                )


def _walk_schema(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise InvalidComponentValue(
                    "Only local JSON Schema references are allowed"
                )
            if key.startswith("x-"):
                raise InvalidComponentValue("Unsupported JSON Schema extension")
            _walk_schema(item)
    elif isinstance(value, list):
        for item in value:
            _walk_schema(item)


def _validate_expression(value: Any) -> None:
    if isinstance(value, ExpressionNode):
        jsonata.Jsonata(value.expr)
    elif isinstance(value, dict):
        if set(value) == {"$expr"}:
            jsonata.Jsonata(value["$expr"])
        else:
            for item in value.values():
                _validate_expression(item)
    elif isinstance(value, list):
        for item in value:
            _validate_expression(item)


def normalize_canonical_input(
    value: dict[str, Any], bindings: dict[str, str]
) -> dict[str, Any]:
    normalized = dict(value)
    for source, target in bindings.items():
        item = normalized.get(source)
        if CANONICAL_FIELD_NORMALIZERS.get(target) == "trim" and isinstance(item, str):
            normalized[source] = item.strip()
        elif CANONICAL_FIELD_NORMALIZERS.get(target) == "e164" and item is not None:
            compact = re.sub(r"[\s()-]", "", item) if isinstance(item, str) else ""
            compact = f"+{compact[2:]}" if compact.startswith("00") else compact
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", compact):
                raise InvalidComponentValue("Phone number must be international E.164")
            normalized[source] = compact
    return normalized


def register_capability_components(registry: object) -> None:
    from control_plane.domain.components import ComponentRegistry

    assert isinstance(registry, ComponentRegistry)
    registry.register(
        ComponentDefinition(
            ComponentKind("capabilities.tenant"),
            TenantCapabilitiesConfig,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
