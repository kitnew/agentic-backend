from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import UUID

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    ValidationError as JsonSchemaValidationError,
)
from pydantic import TypeAdapter, ValidationError

from .errors import InvalidComponentValue, ScopeNotAllowed, UnknownComponentKind
from .model import ComponentAddress, ComponentKind, ScopeType


@dataclass(frozen=True, slots=True)
class ComponentDefinition[T]:
    kind: ComponentKind
    value_type: type[T]
    allowed_scopes: frozenset[ScopeType]
    schema_version: int
    deployment_ref: Callable[[T], UUID] | None = None
    validate_deployment: Callable[[T, object], None] | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("schema version must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def value_schema(self) -> dict[str, Any]:
        return TypeAdapter(self.value_type).json_schema()

    def deserialize(self, value: object) -> T:
        try:
            Draft202012Validator(
                self.value_schema, format_checker=FormatChecker()
            ).validate(value)
            return TypeAdapter(self.value_type).validate_python(value)
        except (JsonSchemaValidationError, ValidationError) as exc:
            raise InvalidComponentValue(str(exc)) from exc

    def serialize(self, value: T) -> Any:
        return TypeAdapter(self.value_type).dump_python(
            value, mode="json", by_alias=True
        )


@dataclass(frozen=True, slots=True)
class ComponentDefinitionEntry:
    key: str
    schema_version: int
    allowed_scopes: tuple[str, ...]
    value_schema: Mapping[str, Any]
    metadata: Mapping[str, object]


class ComponentDefinitionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[ComponentKind, ComponentDefinition[Any]] = {}
        self._frozen = False

    def register(self, definition: ComponentDefinition[Any]) -> None:
        if self._frozen:
            raise RuntimeError("component definition registry is read-only")
        if definition.kind in self._definitions:
            raise ValueError(f"duplicate component kind: {definition.kind}")
        self._definitions[definition.kind] = definition

    @property
    def definitions(self) -> tuple[ComponentDefinition[Any], ...]:
        return tuple(self._definitions.values())

    @property
    def entries(self) -> tuple[ComponentDefinitionEntry, ...]:
        return tuple(
            ComponentDefinitionEntry(
                str(definition.kind),
                definition.schema_version,
                tuple(scope.value for scope in definition.allowed_scopes),
                definition.value_schema,
                definition.metadata,
            )
            for definition in self.definitions
        )

    def freeze(self) -> None:
        self._frozen = True

    def resolve(self, address: ComponentAddress) -> ComponentDefinition[Any]:
        try:
            definition = self._definitions[address.kind]
        except KeyError as exc:
            raise UnknownComponentKind(str(address.kind)) from exc
        if address.scope.type not in definition.allowed_scopes:
            raise ScopeNotAllowed(
                f"{address.scope.type} is not allowed for {address.kind}"
            )
        return definition
