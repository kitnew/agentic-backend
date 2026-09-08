from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.transactions import TelephonyCommandScope
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
    ManagedResourcePreconditionFailed,
)
from control_plane.domain.managed_resources import (
    HANDOFF_DESTINATION_KEY,
    HandoffDestination,
    HandoffDestinationRef,
    InboundRoute,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
    normalize_e164,
)


class TelephonyService:
    def __init__(self, command_scope: TelephonyCommandScope) -> None:
        self._command_scope = command_scope

    async def create_assignment(
        self,
        tenant_id: str,
        phone_number: str,
        principal: str,
        idempotency_key: str,
    ) -> PhoneNumberAssignment:
        phone_number = self._phone(phone_number)
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "phone_number": phone_number}
        )
        async with self._command_scope() as (assignments, _, replays):
            replay = await replays.get(
                principal, "telephony.assignment.create", idempotency_key
            )
            if replay is not None:
                return self._assignment_replay(replay, fingerprint)
            value = await assignments.create(tenant_id, phone_number, principal)
            await replays.add(
                principal,
                "telephony.assignment.create",
                idempotency_key,
                fingerprint,
                self._result(value),
            )
        return value

    async def get_assignment(
        self, tenant_id: str, ref: PhoneNumberAssignmentRef
    ) -> PhoneNumberAssignment:
        async with self._command_scope() as (assignments, _, _replays):
            value = await assignments.get(ref)
            self._require_tenant(value, tenant_id)
            return value

    async def list_assignments(self, tenant_id: str) -> list[PhoneNumberAssignment]:
        async with self._command_scope() as (assignments, _, _replays):
            return list(await assignments.list(tenant_id))

    async def enable_assignment(
        self,
        tenant_id: str,
        ref: PhoneNumberAssignmentRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> PhoneNumberAssignment:
        return await self._set_assignment_enabled(
            tenant_id, ref, True, expected_token, principal, idempotency_key
        )

    async def disable_assignment(
        self,
        tenant_id: str,
        ref: PhoneNumberAssignmentRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> PhoneNumberAssignment:
        return await self._set_assignment_enabled(
            tenant_id, ref, False, expected_token, principal, idempotency_key
        )

    async def _set_assignment_enabled(
        self,
        tenant_id: str,
        ref: PhoneNumberAssignmentRef,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> PhoneNumberAssignment:
        operation = f"telephony.assignment.{'enable' if enabled else 'disable'}"
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (assignments, _, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._assignment_replay(replay, fingerprint)
            current = await assignments.get(ref, lock=True)
            self._require_tenant(current, tenant_id)
            self._check_precondition(current, expected_token)
            self._require_state_change("phone number assignment", current.enabled, enabled)
            value = await assignments.set_enabled(current, enabled, principal)
            await replays.add(
                principal, operation, idempotency_key, fingerprint, self._result(value)
            )
        return value

    async def resolve_inbound(self, phone_number: str) -> InboundRoute:
        phone_number = self._phone(phone_number)
        async with self._command_scope() as (assignments, _, _replays):
            assignment = await assignments.resolve(phone_number)
        return InboundRoute(
            assignment.tenant_id,
            assignment.phone_number,
            opaque_concurrency_token(
                {
                    "assignment_id": str(assignment.ref.value),
                    "generation": assignment.generation,
                    "tenant_id": assignment.tenant_id,
                    "phone_number": assignment.phone_number,
                }
            ),
        )

    async def create_destination(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        principal: str,
        idempotency_key: str,
    ) -> HandoffDestination:
        key = self._key(key)
        description = self._description(description)
        phone_number = self._phone(phone_number)
        fingerprint = request_fingerprint(
            {
                "tenant_id": tenant_id,
                "key": key,
                "description": description,
                "phone_number": phone_number,
            }
        )
        async with self._command_scope() as (_, destinations, replays):
            replay = await replays.get(
                principal, "telephony.destination.create", idempotency_key
            )
            if replay is not None:
                return self._destination_replay(replay, fingerprint)
            value = await destinations.create(
                tenant_id, key, description, phone_number, principal
            )
            await replays.add(
                principal,
                "telephony.destination.create",
                idempotency_key,
                fingerprint,
                self._result(value),
            )
        return value

    async def update_destination(
        self,
        tenant_id: str,
        ref: HandoffDestinationRef,
        description: str,
        phone_number: str,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> HandoffDestination:
        description = self._description(description)
        phone_number = self._phone(phone_number)
        fingerprint = request_fingerprint(
            {
                "tenant_id": tenant_id,
                "id": str(ref.value),
                "description": description,
                "phone_number": phone_number,
                "if_match": expected_token,
            }
        )
        async with self._command_scope() as (_, destinations, replays):
            replay = await replays.get(
                principal, "telephony.destination.update", idempotency_key
            )
            if replay is not None:
                return self._destination_replay(replay, fingerprint)
            current = await destinations.get(ref, lock=True)
            self._require_tenant(current, tenant_id)
            self._check_precondition(current, expected_token)
            value = await destinations.update(
                current, description, phone_number, principal
            )
            await replays.add(
                principal,
                "telephony.destination.update",
                idempotency_key,
                fingerprint,
                self._result(value),
            )
        return value

    async def get_destination(
        self, tenant_id: str, ref: HandoffDestinationRef
    ) -> HandoffDestination:
        async with self._command_scope() as (_, destinations, _replays):
            value = await destinations.get(ref)
            self._require_tenant(value, tenant_id)
            return value

    async def list_destinations(self, tenant_id: str) -> list[HandoffDestination]:
        async with self._command_scope() as (_, destinations, _replays):
            return list(await destinations.list(tenant_id))

    async def enable_destination(
        self,
        tenant_id: str,
        ref: HandoffDestinationRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> HandoffDestination:
        return await self._set_destination_enabled(
            tenant_id, ref, True, expected_token, principal, idempotency_key
        )

    async def disable_destination(
        self,
        tenant_id: str,
        ref: HandoffDestinationRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> HandoffDestination:
        return await self._set_destination_enabled(
            tenant_id, ref, False, expected_token, principal, idempotency_key
        )

    async def _set_destination_enabled(
        self,
        tenant_id: str,
        ref: HandoffDestinationRef,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> HandoffDestination:
        operation = f"telephony.destination.{'enable' if enabled else 'disable'}"
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (_, destinations, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._destination_replay(replay, fingerprint)
            current = await destinations.get(ref, lock=True)
            self._require_tenant(current, tenant_id)
            self._check_precondition(current, expected_token)
            self._require_state_change("handoff destination", current.enabled, enabled)
            value = await destinations.set_enabled(current, enabled, principal)
            await replays.add(
                principal, operation, idempotency_key, fingerprint, self._result(value)
            )
        return value

    @staticmethod
    def concurrency_token(value: PhoneNumberAssignment | HandoffDestination) -> str:
        return opaque_concurrency_token(
            {"id": str(value.ref.value), "generation": value.generation}
        )

    @staticmethod
    def _phone(value: str) -> str:
        try:
            return normalize_e164(value)
        except ValueError as error:
            raise InvalidManagedResource(str(error)) from error

    @staticmethod
    def _key(value: str) -> str:
        value = value.strip()
        if not HANDOFF_DESTINATION_KEY.fullmatch(value):
            raise InvalidManagedResource("key must match ^[a-z][a-z0-9_]{0,63}$")
        return value

    @staticmethod
    def _description(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 1000:
            raise InvalidManagedResource(
                "description must be non-blank and at most 1000 characters"
            )
        return value

    @staticmethod
    def _require_tenant(
        value: PhoneNumberAssignment | HandoffDestination, tenant_id: str
    ) -> None:
        if value.tenant_id != tenant_id:
            raise ManagedResourceNotFound(f"resource {value.ref.value} not found")

    def _check_precondition(
        self, value: PhoneNumberAssignment | HandoffDestination, token: str
    ) -> None:
        if self.concurrency_token(value) != token:
            raise ManagedResourcePreconditionFailed("resource precondition failed")

    @staticmethod
    def _require_state_change(kind: str, current: bool, requested: bool) -> None:
        if current == requested:
            raise ManagedResourceConflict(
                f"{kind} is already {'enabled' if requested else 'disabled'}"
            )

    @staticmethod
    def _result(value: PhoneNumberAssignment | HandoffDestination) -> dict[str, Any]:
        result = asdict(value)
        result["id"] = str(result.pop("ref")["value"])
        for key in ("created_at", "updated_at"):
            result[key] = result[key].isoformat()
        return result

    @staticmethod
    def _check_replay(replay: StoredReplay, fingerprint: str) -> dict[str, Any]:
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        return replay.logical_result

    def _assignment_replay(
        self, replay: StoredReplay, fingerprint: str
    ) -> PhoneNumberAssignment:
        value = self._check_replay(replay, fingerprint)
        return PhoneNumberAssignment(
            PhoneNumberAssignmentRef(UUID(value["id"])),
            value["tenant_id"],
            value["phone_number"],
            value["enabled"],
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            value["created_by"],
            datetime.fromisoformat(value["updated_at"]),
            value["updated_by"],
        )

    def _destination_replay(
        self, replay: StoredReplay, fingerprint: str
    ) -> HandoffDestination:
        value = self._check_replay(replay, fingerprint)
        return HandoffDestination(
            HandoffDestinationRef(UUID(value["id"])),
            value["tenant_id"],
            value["key"],
            value["description"],
            value["phone_number"],
            value["enabled"],
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            value["created_by"],
            datetime.fromisoformat(value["updated_at"]),
            value["updated_by"],
        )
