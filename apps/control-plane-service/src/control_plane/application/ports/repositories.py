from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from control_plane.domain.catalogs import CatalogStatus, InteractionMode, Profile
from control_plane.domain.components import ComponentAddress, ComponentDefinition
from control_plane.domain.live_components import LiveComponentState
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialScope,
    DeploymentCapabilities,
    DeploymentKind,
    HandoffDestination,
    HandoffDestinationRef,
    IntegrationConnection,
    IntegrationConnectionRef,
    ModelDeployment,
    ModelDeploymentRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
    ProviderConnection,
    ProviderConnectionRef,
)


class StoredDraft(Protocol):
    schema_version: int
    value: Mapping[str, Any]
    version: int
    based_on_revision_id: UUID | None
    updated_at: datetime
    updated_by: str


class StoredRevision(Protocol):
    id: UUID
    revision_number: int
    schema_version: int
    value: Mapping[str, Any]
    based_on_revision_id: UUID | None
    restored_from_revision_id: UUID | None
    created_at: datetime
    created_by: str


class ComponentRepository(Protocol):
    async def get_component(
        self, address: ComponentAddress, *, lock: bool = False
    ) -> tuple[bool, StoredDraft | None, StoredRevision | None]: ...

    async def save_draft(
        self,
        address: ComponentAddress,
        value: Mapping[str, Any],
        schema_version: int,
        expected_draft_version: int | None,
        expected_active_revision_id: UUID | None,
        actor: str,
    ) -> StoredDraft: ...
    async def discard_draft(
        self, address: ComponentAddress, expected_draft_version: int
    ) -> None: ...
    async def publish_draft(
        self,
        address: ComponentAddress,
        expected_draft_version: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> StoredRevision: ...
    async def rollback(
        self,
        address: ComponentAddress,
        revision_number: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> StoredRevision: ...
    async def get_draft(self, address: ComponentAddress) -> StoredDraft | None: ...
    async def get_active(self, address: ComponentAddress) -> StoredRevision | None: ...
    async def get_revision(
        self, address: ComponentAddress, revision_number: int
    ) -> StoredRevision | None: ...
    async def list_revisions(
        self, address: ComponentAddress, limit: int
    ) -> Sequence[StoredRevision]: ...


class LiveComponentRepository(Protocol):
    async def get(
        self, address: ComponentAddress, *, lock: bool = False
    ) -> LiveComponentState[Any] | None: ...
    async def set(
        self,
        address: ComponentAddress,
        value: Mapping[str, Any],
        schema_version: int,
        actor: str,
    ) -> LiveComponentState[Any]: ...


class SystemConfigurationRepository(LiveComponentRepository, Protocol):
    async def get_deployment(
        self, ref: ModelDeploymentRef, *, lock: bool = False
    ) -> ModelDeployment: ...
    async def get_connection(
        self, ref: ProviderConnectionRef, *, lock: bool = False
    ) -> ProviderConnection: ...
    async def get_credential(
        self, ref: CredentialRef, *, lock: bool = False
    ) -> Credential: ...


class PlatformRepository(ComponentRepository, Protocol):
    async def get_profile(self, key: str, *, lock: bool = False) -> Profile | None: ...
    async def list_profiles(self, *, lock: bool = False) -> Sequence[Profile]: ...
    async def put_profile(
        self,
        key: str,
        name: str,
        description: str,
        status: CatalogStatus,
        actor: str,
    ) -> Profile: ...
    async def get_interaction_mode(
        self, key: str, *, lock: bool = False
    ) -> InteractionMode | None: ...
    async def list_interaction_modes(
        self, *, lock: bool = False
    ) -> Sequence[InteractionMode]: ...
    async def put_interaction_mode(
        self,
        key: str,
        name: str,
        description: str,
        status: CatalogStatus,
        actor: str,
    ) -> InteractionMode: ...


class CredentialRepository(Protocol):
    async def create(
        self, scope: CredentialScope, name: str, secret: str, actor: str
    ) -> Credential: ...
    async def get(self, ref: CredentialRef, *, lock: bool = False) -> Credential: ...
    async def list(
        self, scope: CredentialScope | None = None
    ) -> Sequence[Credential]: ...
    async def rotate(
        self, credential: Credential, secret: str, actor: str
    ) -> Credential: ...
    async def revoke(self, credential: Credential, actor: str) -> Credential: ...
    async def has_enabled_provider_connections(self, ref: CredentialRef) -> bool: ...
    async def has_enabled_integration_connections(self, ref: CredentialRef) -> bool: ...


class IntegrationRepository(Protocol):
    async def create(
        self,
        tenant_id: str,
        key: str,
        integration_kind: str,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        actor: str,
    ) -> IntegrationConnection: ...
    async def update(
        self,
        connection: IntegrationConnection,
        config: dict[str, object],
        credential_ref: CredentialRef | None,
        actor: str,
    ) -> IntegrationConnection: ...
    async def set_enabled(
        self,
        connection: IntegrationConnection,
        enabled: bool,
        actor: str,
    ) -> IntegrationConnection: ...
    async def get(
        self,
        ref: IntegrationConnectionRef,
        *,
        lock: bool = False,
    ) -> IntegrationConnection: ...
    async def get_by_key(self, tenant_id: str, key: str) -> IntegrationConnection: ...
    async def list(self, tenant_id: str) -> Sequence[IntegrationConnection]: ...
    async def get_credential(
        self,
        ref: CredentialRef,
        *,
        lock: bool = False,
    ) -> Credential: ...


class PhoneNumberAssignmentRepository(Protocol):
    async def create(
        self, tenant_id: str, phone_number: str, actor: str
    ) -> PhoneNumberAssignment: ...
    async def set_enabled(
        self, assignment: PhoneNumberAssignment, enabled: bool, actor: str
    ) -> PhoneNumberAssignment: ...
    async def get(
        self, ref: PhoneNumberAssignmentRef, *, lock: bool = False
    ) -> PhoneNumberAssignment: ...
    async def list(self, tenant_id: str) -> Sequence[PhoneNumberAssignment]: ...
    async def resolve(self, phone_number: str) -> PhoneNumberAssignment: ...


class HandoffDestinationRepository(Protocol):
    async def create(
        self,
        tenant_id: str,
        key: str,
        description: str,
        phone_number: str,
        actor: str,
    ) -> HandoffDestination: ...
    async def update(
        self,
        destination: HandoffDestination,
        description: str,
        phone_number: str,
        actor: str,
    ) -> HandoffDestination: ...
    async def set_enabled(
        self, destination: HandoffDestination, enabled: bool, actor: str
    ) -> HandoffDestination: ...
    async def get(
        self, ref: HandoffDestinationRef, *, lock: bool = False
    ) -> HandoffDestination: ...
    async def list(self, tenant_id: str) -> Sequence[HandoffDestination]: ...


class ProviderRepository(Protocol):
    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        config: dict[str, object],
        actor: str,
    ) -> ProviderConnection: ...
    async def update_connection(
        self,
        connection: ProviderConnection,
        credential_ref: CredentialRef,
        config: dict[str, object],
        actor: str,
    ) -> ProviderConnection: ...
    async def set_connection_enabled(
        self, connection: ProviderConnection, enabled: bool, actor: str
    ) -> ProviderConnection: ...
    async def get_connection(
        self, ref: ProviderConnectionRef, *, lock: bool = False
    ) -> ProviderConnection: ...
    async def list_connections(self) -> Sequence[ProviderConnection]: ...
    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        kind: DeploymentKind,
        config: dict[str, object],
        capabilities: DeploymentCapabilities,
        actor: str,
    ) -> ModelDeployment: ...
    async def update_deployment(
        self,
        deployment: ModelDeployment,
        connection_ref: ProviderConnectionRef,
        config: dict[str, object],
        capabilities: DeploymentCapabilities,
        actor: str,
    ) -> ModelDeployment: ...
    async def set_deployment_enabled(
        self, deployment: ModelDeployment, enabled: bool, actor: str
    ) -> ModelDeployment: ...
    async def get_deployment(
        self, ref: ModelDeploymentRef, *, lock: bool = False
    ) -> ModelDeployment: ...
    async def list_deployments(self) -> Sequence[ModelDeployment]: ...
    async def has_enabled_deployments(self, ref: ProviderConnectionRef) -> bool: ...
    async def is_referenced_by_system_configuration(
        self, ref: ModelDeploymentRef
    ) -> bool: ...
    async def system_configuration_references(
        self, ref: ModelDeploymentRef
    ) -> Sequence[tuple[str, Mapping[str, Any]]]: ...
    async def get_credential(
        self, ref: CredentialRef, *, lock: bool = False
    ) -> Credential: ...
    async def credential_secret(self, credential: Credential) -> str: ...
