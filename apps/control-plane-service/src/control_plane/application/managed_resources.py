from collections.abc import Sequence
from typing import Protocol

from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    DeploymentKind,
    HandoffDestination,
    HandoffDestinationRef,
    IntegrationConnection,
    IntegrationConnectionRef,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.domain.providers import ProviderRegistry


class ManagedResourceRepository(Protocol):
    async def create_credential(
        self, name: str, secret: str, actor: str
    ) -> Credential: ...
    async def rotate_credential(
        self, ref: CredentialRef, secret: str, actor: str
    ) -> Credential: ...
    async def revoke_credential(self, ref: CredentialRef, actor: str) -> Credential: ...
    async def get_credential(self, ref: CredentialRef) -> Credential: ...
    async def list_credentials(self) -> Sequence[Credential]: ...
    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        config: dict[str, object],
        enabled: bool,
        actor: str,
    ) -> ProviderConnection: ...
    async def update_connection(
        self,
        ref: ProviderConnectionRef,
        credential_ref: CredentialRef,
        config: dict[str, object],
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection: ...
    async def set_connection_enabled(
        self,
        ref: ProviderConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection: ...
    async def get_connection(
        self, ref: ProviderConnectionRef
    ) -> ProviderConnection: ...
    async def list_connections(self) -> Sequence[ProviderConnection]: ...
    async def create_integration_connection(
        self,
        tenant_id: str,
        key: str,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        enabled: bool,
        actor: str,
    ) -> IntegrationConnection: ...
    async def update_integration_connection(
        self,
        ref: IntegrationConnectionRef,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection: ...
    async def set_integration_connection_enabled(
        self,
        ref: IntegrationConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection: ...
    async def get_integration_connection(
        self, ref: IntegrationConnectionRef
    ) -> IntegrationConnection: ...
    async def list_integration_connections(
        self, tenant_id: str | None = None
    ) -> Sequence[IntegrationConnection]: ...
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
    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        kind: DeploymentKind,
        config: dict[str, object],
        enabled: bool,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment: ...
    async def update_deployment(
        self,
        ref: ModelDeploymentRef,
        connection_ref: ProviderConnectionRef,
        config: dict[str, object],
        expected_generation: int,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment: ...
    async def set_deployment_enabled(
        self,
        ref: ModelDeploymentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ModelDeployment: ...
    async def get_deployment(self, ref: ModelDeploymentRef) -> ModelDeployment: ...
    async def list_deployments(self) -> Sequence[ModelDeployment]: ...


class ManagedResourceService:
    def __init__(
        self, registry: ProviderRegistry, repository: ManagedResourceRepository
    ) -> None:
        self._registry = registry
        self._repository = repository

    async def create_credential(self, name: str, secret: str, actor: str) -> Credential:
        return await self._repository.create_credential(name, secret, actor)

    async def rotate_credential(
        self, ref: CredentialRef, secret: str, actor: str
    ) -> Credential:
        return await self._repository.rotate_credential(ref, secret, actor)

    async def revoke_credential(self, ref: CredentialRef, actor: str) -> Credential:
        return await self._repository.revoke_credential(ref, actor)

    async def get_credential(self, ref: CredentialRef) -> Credential:
        return await self._repository.get_credential(ref)

    async def list_credentials(self) -> Sequence[Credential]:
        return await self._repository.list_credentials()

    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        config: object,
        enabled: bool,
        actor: str,
    ) -> ProviderConnection:
        validated = self._registry.resolve(provider_kind).validate_connection(config)
        return await self._repository.create_connection(
            key, provider_kind, credential_ref, validated, enabled, actor
        )

    async def update_connection(
        self,
        ref: ProviderConnectionRef,
        credential_ref: CredentialRef,
        config: object,
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection:
        current = await self._repository.get_connection(ref)
        validated = self._registry.resolve(current.provider_kind).validate_connection(
            config
        )
        return await self._repository.update_connection(
            ref, credential_ref, validated, expected_generation, actor
        )

    async def set_connection_enabled(
        self,
        ref: ProviderConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ProviderConnection:
        return await self._repository.set_connection_enabled(
            ref, enabled, expected_generation, actor
        )

    async def get_connection(self, ref: ProviderConnectionRef) -> ProviderConnection:
        return await self._repository.get_connection(ref)

    async def list_connections(self) -> Sequence[ProviderConnection]:
        return await self._repository.list_connections()

    async def create_integration_connection(
        self,
        tenant_id: str,
        key: str,
        config: object,
        credential_ref: CredentialRef | None,
        enabled: bool,
        actor: str,
    ) -> IntegrationConnection:
        return await self._repository.create_integration_connection(
            tenant_id,
            key,
            self._validate_http_connection(config, credential_ref),
            credential_ref,
            enabled,
            actor,
        )

    async def update_integration_connection(
        self,
        ref: IntegrationConnectionRef,
        config: object,
        credential_ref: CredentialRef | None,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection:
        return await self._repository.update_integration_connection(
            ref,
            self._validate_http_connection(config, credential_ref),
            credential_ref,
            expected_generation,
            actor,
        )

    async def set_integration_connection_enabled(
        self,
        ref: IntegrationConnectionRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> IntegrationConnection:
        return await self._repository.set_integration_connection_enabled(
            ref, enabled, expected_generation, actor
        )

    async def get_integration_connection(
        self, ref: IntegrationConnectionRef
    ) -> IntegrationConnection:
        return await self._repository.get_integration_connection(ref)

    async def list_integration_connections(
        self, tenant_id: str | None = None
    ) -> Sequence[IntegrationConnection]:
        return await self._repository.list_integration_connections(tenant_id)

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

    @staticmethod
    def _validate_http_connection(
        config: object, credential_ref: CredentialRef | None
    ) -> dict[str, object]:
        from contracts.integration import HttpConnectionConfiguration

        validated = HttpConnectionConfiguration.model_validate(config)
        if (validated.authentication.type == "none") != (credential_ref is None):
            raise InvalidManagedResource(
                "credential_ref must match HTTP authentication mode"
            )
        return validated.model_dump(mode="json")

    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        kind: DeploymentKind,
        config: object,
        enabled: bool,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment:
        connection = await self._repository.get_connection(connection_ref)
        validated = self._registry.resolve(
            connection.provider_kind
        ).validate_deployment(kind, config)
        self._validate_capabilities(
            kind, llm_capabilities, realtime_capabilities, stt_capabilities
        )
        return await self._repository.create_deployment(
            key,
            connection_ref,
            kind,
            validated,
            enabled,
            actor,
            llm_capabilities,
            realtime_capabilities,
            stt_capabilities,
        )

    async def update_deployment(
        self,
        ref: ModelDeploymentRef,
        connection_ref: ProviderConnectionRef,
        config: object,
        expected_generation: int,
        actor: str,
        llm_capabilities: LLMCapabilities | None = None,
        realtime_capabilities: RealtimeCapabilities | None = None,
        stt_capabilities: STTCapabilities | None = None,
    ) -> ModelDeployment:
        current = await self._repository.get_deployment(ref)
        connection = await self._repository.get_connection(connection_ref)
        validated = self._registry.resolve(
            connection.provider_kind
        ).validate_deployment(current.deployment_kind, config)
        self._validate_capabilities(
            current.deployment_kind,
            llm_capabilities,
            realtime_capabilities,
            stt_capabilities,
        )
        return await self._repository.update_deployment(
            ref,
            connection_ref,
            validated,
            expected_generation,
            actor,
            llm_capabilities,
            realtime_capabilities,
            stt_capabilities,
        )

    @staticmethod
    def _validate_capabilities(
        kind: DeploymentKind,
        llm: LLMCapabilities | None,
        realtime: RealtimeCapabilities | None,
        stt: STTCapabilities | None,
    ) -> None:
        expected = {
            DeploymentKind.LLM: llm,
            DeploymentKind.REALTIME: realtime,
            DeploymentKind.STT: stt,
        }
        supplied = sum(value is not None for value in (llm, realtime, stt))
        valid = (
            expected[kind] is not None and supplied == 1
            if kind in expected
            else supplied == 0
        )
        if not valid:
            raise InvalidManagedResource(
                f"capabilities do not match deployment_kind={kind.value}"
            )

    async def set_deployment_enabled(
        self,
        ref: ModelDeploymentRef,
        enabled: bool,
        expected_generation: int,
        actor: str,
    ) -> ModelDeployment:
        return await self._repository.set_deployment_enabled(
            ref, enabled, expected_generation, actor
        )

    async def get_deployment(self, ref: ModelDeploymentRef) -> ModelDeployment:
        return await self._repository.get_deployment(ref)

    async def list_deployments(self) -> Sequence[ModelDeployment]:
        return await self._repository.list_deployments()
