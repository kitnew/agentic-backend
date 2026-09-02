from __future__ import annotations

import re
from typing import Any, Literal

from contracts.http_operation import ExpressionNode, HttpOperation, MappingTemplate
from contracts.tenant_components import PostCallActionInput
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.domain.capabilities import (
    IntegrationConnectionRef,
    validate_mapping_expressions,
)
from control_plane.domain.components import (
    ComponentDefinition,
    ComponentKind,
    ScopeType,
)
from control_plane.domain.components.errors import InvalidComponentValue


class _PostCallModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HttpPostCallExecution(_PostCallModel):
    plan_type: Literal["http.request.v1"] = "http.request.v1"
    integration_connection_ref: IntegrationConnectionRef
    method: str
    path: str | ExpressionNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: Any = Field(default_factory=lambda: {"codec": "none"})
    response: Any = Field(default_factory=lambda: {"codec": "none"})
    timeout_seconds: int
    success_statuses: list[int] | None = Field(default=None, max_length=20)
    result_schema: dict[str, object] | None = None

    @model_validator(mode="after")
    def operation_is_valid(self) -> HttpPostCallExecution:
        operation = self.model_dump(
            mode="python",
            exclude={"plan_type", "integration_connection_ref", "result_schema"},
        )
        if isinstance(self.path, ExpressionNode):
            operation["path"] = self.path.model_dump(by_alias=True)
        HttpOperation.model_validate(operation | {"connection": "integration"})
        validate_mapping_expressions(self.path)
        validate_mapping_expressions(self.query)
        validate_mapping_expressions(self.request)
        validate_mapping_expressions(self.response)
        if self.result_schema is not None:
            try:
                Draft202012Validator.check_schema(self.result_schema)
            except SchemaError as error:
                raise InvalidComponentValue(
                    f"invalid result schema: {error.message}"
                ) from error
        return self


class TenantPostCallAction(_PostCallModel):
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    type: Literal["http"] = "http"
    inputs: dict[str, PostCallActionInput] = Field(default_factory=dict, max_length=10)
    execution: HttpPostCallExecution

    @model_validator(mode="after")
    def input_keys_are_valid(self) -> TenantPostCallAction:
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) for key in self.inputs):
            raise InvalidComponentValue("post-call input key is invalid")
        return self


class TenantPostCallConfig(_PostCallModel):
    actions: list[TenantPostCallAction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def action_ids_are_unique(self) -> TenantPostCallConfig:
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise InvalidComponentValue("post-call action IDs must be unique")
        return self


def register_post_call_components(registry: object) -> None:
    from control_plane.domain.components import ComponentRegistry

    assert isinstance(registry, ComponentRegistry)
    registry.register(
        ComponentDefinition(
            ComponentKind("post_call.tenant"),
            TenantPostCallConfig,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
