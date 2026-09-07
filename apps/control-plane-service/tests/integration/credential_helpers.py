import base64
from uuid import uuid4

from control_plane.application.credentials import CredentialService
from control_plane.application.providers import (
    ProviderService,
    ProviderValidationResult,
)
from control_plane.domain.managed_resources import (
    CredentialRef,
    DeploymentCapabilities,
    DeploymentKind,
    ModelDeployment,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
)
from control_plane.domain.registries import DeploymentKindRegistry, ProviderKindRegistry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.provider_transactions import (
    provider_command_scope,
)


class _UnusedValidator:
    async def validate_connection(self, *_args):
        return ProviderValidationResult(True, True)

    async def validate_deployment(self, *_args):
        return ProviderValidationResult(True, True)


def credential_service(database: Database) -> CredentialService:
    cipher = CredentialCipher(base64.b64encode(b"0" * 32).decode())
    return CredentialService(credential_command_scope(database.sessions, cipher))


def provider_service(database: Database) -> ProviderService:
    cipher = CredentialCipher(base64.b64encode(b"0" * 32).decode())
    return ProviderService(
        provider_command_scope(database.sessions, cipher),
        ProviderKindRegistry(),
        DeploymentKindRegistry(),
        _UnusedValidator(),
    )


async def create_provider_connection(
    service: ProviderService,
    key: str,
    provider_kind: str,
    credential_ref: CredentialRef,
    connection_config: object,
    *,
    enabled: bool = True,
) -> ProviderConnection:
    value = await service.create_connection(
        key,
        provider_kind,
        credential_ref,
        connection_config,
        "test",
        str(uuid4()),
    )
    if enabled:
        value = await service.enable_connection(
            value.ref, service.concurrency_token(value), "test", str(uuid4())
        )
    return value


async def create_model_deployment(
    service: ProviderService,
    key: str,
    connection_ref: ProviderConnectionRef,
    deployment_kind: DeploymentKind,
    deployment_config: object,
    capabilities: DeploymentCapabilities,
    *,
    enabled: bool = True,
) -> ModelDeployment:
    value = await service.create_deployment(
        key,
        connection_ref,
        deployment_kind,
        deployment_config,
        capabilities,
        "test",
        str(uuid4()),
    )
    if enabled:
        value = await service.enable_deployment(
            value.ref, service.concurrency_token(value), "test", str(uuid4())
        )
    return value


async def create_platform_credential(
    database: Database, name: str, secret: str = "secret", actor: str = "test"
):
    return await credential_service(database).create(
        PlatformCredentialScope(), name, secret, actor, str(uuid4())
    )
