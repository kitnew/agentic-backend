from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.integration import RESERVED_HTTP_HEADERS


class _HttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpressionNode(_HttpModel):
    expr: str = Field(alias="$expr", min_length=1, max_length=20_000)


type MappingScalar = str | int | float | bool | None
type MappingTemplate = MappingScalar | ExpressionNode | dict[str, object] | list[object]


def _validate_mapping(value: object) -> object:
    if isinstance(value, dict):
        if "$expr" in value:
            if set(value) != {"$expr"} or not isinstance(value["$expr"], str) or not value["$expr"].strip():
                raise ValueError("expression nodes must contain only a non-empty $expr")
            return value
        for item in value.values():
            _validate_mapping(item)
    elif isinstance(value, list):
        for item in value:
            _validate_mapping(item)
    elif not isinstance(value, (str, int, float, bool)) and value is not None:
        raise ValueError("mapping templates must contain JSON-compatible values")
    return value


class HttpRequestSpec(_HttpModel):
    codec: Literal["none", "json", "text"]
    mapping: MappingTemplate | None = None
    content_type: str | None = Field(default=None, pattern=r"^[^\s/]+/[^\s]+$")

    @field_validator("mapping")
    @classmethod
    def mapping_is_typed(cls, value: MappingTemplate | None) -> MappingTemplate | None:
        return _validate_mapping(value) if value is not None else None


class HttpResponseSpec(_HttpModel):
    codec: Literal["none", "json", "text"]
    mapping: MappingTemplate | None = None

    @field_validator("mapping")
    @classmethod
    def mapping_is_typed(cls, value: MappingTemplate | None) -> MappingTemplate | None:
        return _validate_mapping(value) if value is not None else None


class HttpBodyBinding(_HttpModel):
    representation_id: UUID
    payload_path: str = Field(min_length=1, max_length=2048)


class HttpOperation(_HttpModel):
    type: Literal["http"] = "http"
    connection: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str | ExpressionNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: HttpRequestSpec = Field(default_factory=lambda: HttpRequestSpec(codec="none"))
    response: HttpResponseSpec = Field(default_factory=lambda: HttpResponseSpec(codec="none"))
    timeout_seconds: float = Field(gt=0, le=60)
    success_statuses: list[int] | None = Field(default=None, max_length=20)

    @field_validator("query")
    @classmethod
    def query_is_typed(cls, value: dict[str, MappingTemplate] | None) -> dict[str, MappingTemplate] | None:
        if value is not None:
            for item in value.values():
                _validate_mapping(item)
        return value

    @field_validator("headers")
    @classmethod
    def headers_are_non_system(cls, value: dict[str, str]) -> dict[str, str]:
        if any(name.lower() in RESERVED_HTTP_HEADERS or any(char in name for char in "\r\n:") or any(char in header for char in "\r\n") for name, header in value.items()):
            raise ValueError("operation headers contain a reserved or invalid header")
        return value

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str | ExpressionNode | None) -> str | ExpressionNode | None:
        if isinstance(value, str):
            parsed = urlsplit(value)
            if not value or value.startswith("//") or parsed.scheme or parsed.netloc or parsed.username or parsed.password or parsed.fragment or parsed.query:
                raise ValueError("HTTP operation path must be relative")
        return value


class HttpRequestPlanV1(_HttpModel):
    plan_type: Literal["http.request.v1"] = "http.request.v1"
    integration_id: UUID
    operation_id: UUID
    capability: object | None = None
    body_bindings: list[HttpBodyBinding] = Field(default_factory=list)
    payload: object | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str | ExpressionNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: HttpRequestSpec = Field(default_factory=lambda: HttpRequestSpec(codec="none"))
    response: HttpResponseSpec = Field(default_factory=lambda: HttpResponseSpec(codec="none"))
    timeout_seconds: float = Field(gt=0, le=60)
    success_statuses: list[int] | None = Field(default=None, max_length=20)
    result_schema: dict[str, object] | None = None
