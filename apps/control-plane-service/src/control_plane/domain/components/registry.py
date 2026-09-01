from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .errors import InvalidComponentValue, ScopeNotAllowed, UnknownComponentKind
from .model import ComponentAddress, ComponentKind, ScopeType


@dataclass(frozen=True, slots=True)
class ComponentDefinition[T]:
    kind: ComponentKind
    value_type: type[T]
    allowed_scopes: frozenset[ScopeType]
    current_schema_version: int

    def __post_init__(self) -> None:
        if self.current_schema_version < 1:
            raise ValueError("schema version must be positive")

    def deserialize(self, value: object) -> T:
        try:
            return TypeAdapter(self.value_type).validate_python(value)
        except ValidationError as exc:
            raise InvalidComponentValue(str(exc)) from exc

    def serialize(self, value: T) -> Any:
        return TypeAdapter(self.value_type).dump_python(value, mode="json")


class ComponentRegistry:
    def __init__(self) -> None:
        self._definitions: dict[ComponentKind, ComponentDefinition[Any]] = {}

    def register(self, definition: ComponentDefinition[Any]) -> None:
        if definition.kind in self._definitions:
            raise ValueError(f"duplicate component kind: {definition.kind}")
        self._definitions[definition.kind] = definition

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
