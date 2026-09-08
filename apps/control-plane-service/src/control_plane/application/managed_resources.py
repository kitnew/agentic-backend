from collections.abc import Sequence
from typing import Protocol

from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import (
    HandoffDestination,
    HandoffDestinationRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
)


class ManagedResourceRepository(Protocol):
    async def create_handoff_destination(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        enabled: bool,
        actor: str,
    ) -> HandoffDestination: ...
    async def update_handoff_destination(
        self,
        ref: HandoffDestinationRef,
        description: str,
        phone_number: str,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination: ...
    async def set_handoff_destination_enabled(
        self,
        ref: HandoffDestinationRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination: ...
    async def get_handoff_destination(
        self, ref: HandoffDestinationRef
    ) -> HandoffDestination: ...
    async def list_handoff_destinations(
        self, tenant_id: str | None = None
    ) -> Sequence[HandoffDestination]: ...
    async def create_phone_number_assignment(
        self,
        tenant_id: str,
        phone_number: str,
        enabled: bool,
        actor: str,
    ) -> PhoneNumberAssignment: ...
    async def set_phone_number_assignment_enabled(
        self,
        ref: PhoneNumberAssignmentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> PhoneNumberAssignment: ...
    async def get_phone_number_assignment(
        self, ref: PhoneNumberAssignmentRef
    ) -> PhoneNumberAssignment: ...
    async def list_phone_number_assignments(
        self, tenant_id: str | None = None
    ) -> Sequence[PhoneNumberAssignment]: ...


class ManagedResourceService:
    def __init__(self, repository: ManagedResourceRepository) -> None:
        self._repository = repository

    async def create_handoff_destination(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        enabled: bool,
        actor: str,
    ) -> HandoffDestination:
        return await self._repository.create_handoff_destination(
            tenant_id,
            self._handoff_key(key),
            self._description(description),
            self._phone(phone_number),
            enabled,
            actor,
        )

    async def update_handoff_destination(
        self,
        ref: HandoffDestinationRef,
        description: str,
        phone_number: str,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination:
        return await self._repository.update_handoff_destination(
            ref,
            self._description(description),
            self._phone(phone_number),
            expected_generation,
            actor,
        )

    async def set_handoff_destination_enabled(
        self,
        ref: HandoffDestinationRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> HandoffDestination:
        return await self._repository.set_handoff_destination_enabled(
            ref, enabled, expected_generation, actor
        )

    async def get_handoff_destination(
        self, ref: HandoffDestinationRef
    ) -> HandoffDestination:
        return await self._repository.get_handoff_destination(ref)

    async def list_handoff_destinations(
        self, tenant_id: str | None = None
    ) -> Sequence[HandoffDestination]:
        return await self._repository.list_handoff_destinations(tenant_id)

    async def create_phone_number_assignment(
        self, tenant_id: str, phone_number: str, enabled: bool, actor: str
    ) -> PhoneNumberAssignment:
        return await self._repository.create_phone_number_assignment(
            tenant_id, self._phone(phone_number), enabled, actor
        )

    async def set_phone_number_assignment_enabled(
        self,
        ref: PhoneNumberAssignmentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> PhoneNumberAssignment:
        return await self._repository.set_phone_number_assignment_enabled(
            ref, enabled, expected_generation, actor
        )

    async def get_phone_number_assignment(
        self, ref: PhoneNumberAssignmentRef
    ) -> PhoneNumberAssignment:
        return await self._repository.get_phone_number_assignment(ref)

    async def list_phone_number_assignments(
        self, tenant_id: str | None = None
    ) -> Sequence[PhoneNumberAssignment]:
        return await self._repository.list_phone_number_assignments(tenant_id)

    @staticmethod
    def _description(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 1000:
            raise InvalidManagedResource(
                "description must be non-blank and at most 1000 characters"
            )
        return value

    @staticmethod
    def _phone(value: str) -> str:
        from control_plane.domain.managed_resources import normalize_e164

        try:
            return normalize_e164(value)
        except ValueError as error:
            raise InvalidManagedResource(str(error)) from error

    @staticmethod
    def _handoff_key(value: str) -> str:
        from control_plane.domain.managed_resources import HANDOFF_DESTINATION_KEY

        value = value.strip()
        if not HANDOFF_DESTINATION_KEY.fullmatch(value):
            raise InvalidManagedResource("key must match ^[a-z][a-z0-9_]{0,63}$")
        return value
