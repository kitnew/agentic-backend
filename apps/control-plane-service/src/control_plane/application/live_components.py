from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.transactions import LiveComponentCommandScope
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.live_components import LiveComponentState


class LiveComponentNotFound(ComponentError):
    code = "live_component_not_found"


class LiveComponentPreconditionFailed(ComponentError):
    code = "precondition_failed"


class LiveComponentService:
    def __init__(
        self,
        registry: ComponentDefinitionRegistry,
        command_scope: LiveComponentCommandScope,
        validator: Callable[[object, ComponentAddress, object], Awaitable[None]]
        | None = None,
    ) -> None:
        self._registry = registry
        self._command_scope = command_scope
        self._validator = validator

    async def get(self, address: ComponentAddress) -> LiveComponentState[Any]:
        self._definition(address)
        async with self._command_scope() as (repository, _):
            value = await repository.get(address)
        if value is None:
            raise LiveComponentNotFound(str(address.kind))
        return replace_value(value, self._definition(address).deserialize(value.value))

    async def set(
        self,
        address: ComponentAddress,
        raw_value: object,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> LiveComponentState[Any]:
        definition = self._definition(address)
        value = definition.deserialize(raw_value)
        serialized = definition.serialize(value)
        operation = f"live_component.set:{address.scope.type.value}:{address.kind}"
        fingerprint = request_fingerprint(
            {"value": serialized, "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._replay(address, definition, replay, fingerprint)
            current = await repository.get(address, lock=True)
            self._check_precondition(current, expected_token)
            if self._validator is not None:
                await self._validator(repository, address, value)
            result = await repository.set(
                address, serialized, definition.schema_version, principal
            )
            await replays.add(
                principal,
                operation,
                idempotency_key,
                fingerprint,
                self._result(result),
            )
        return replace_value(result, value)

    @staticmethod
    def concurrency_token(value: LiveComponentState[Any] | None) -> str:
        if value is None:
            return "*"
        return opaque_concurrency_token(
            {
                "kind": str(value.address.kind),
                "scope": value.address.scope.type.value,
                "scope_key": value.address.scope.key,
                "generation": value.generation,
            }
        )

    def _definition(self, address: ComponentAddress):
        definition = self._registry.resolve(address)
        if definition.metadata.get("lifecycle") != "live":
            raise ValueError(f"{address.kind} is not a live component")
        return definition

    def _check_precondition(
        self, current: LiveComponentState[Any] | None, expected_token: str
    ) -> None:
        if current is None:
            if expected_token != self.concurrency_token(None):
                raise LiveComponentPreconditionFailed(
                    "live component precondition failed"
                )
        elif self.concurrency_token(current) != expected_token:
            raise LiveComponentPreconditionFailed("live component precondition failed")

    @staticmethod
    def _result(value: LiveComponentState[Any]) -> dict[str, Any]:
        return {
            "value": value.value,
            "schema_version": value.schema_version,
            "generation": value.generation,
            "updated_at": value.updated_at.isoformat(),
            "updated_by": value.updated_by,
        }

    def _replay(self, address, definition, replay: StoredReplay, fingerprint: str):
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        result = replay.logical_result
        return LiveComponentState(
            address,
            definition.deserialize(result["value"]),
            result["schema_version"],
            result["generation"],
            datetime.fromisoformat(result["updated_at"]),
            result["updated_by"],
        )


def replace_value(
    state: LiveComponentState[Any], value: Any
) -> LiveComponentState[Any]:
    return LiveComponentState(
        state.address,
        value,
        state.schema_version,
        state.generation,
        state.updated_at,
        state.updated_by,
    )
