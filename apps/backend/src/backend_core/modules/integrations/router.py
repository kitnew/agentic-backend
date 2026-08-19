from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.models import IntegrationConnectionStatus
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    CreateIntegrationConnectionRequest,
    IntegrationConnectionResponse,
    IntegrationTestResponse,
    SetIntegrationSecretRequest,
    UpdateIntegrationConnectionRequest,
)
from backend_core.modules.integrations.service import (
    IntegrationConnectionError,
    IntegrationConnectionService,
    IntegrationConnectionView,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/integration-connections",
    tags=["admin:integrations"],
    dependencies=[Depends(require_admin)],
)


def service(session: DatabaseSession, request: Request) -> IntegrationConnectionService:
    # The root key stays deployment-owned; integration values stay database-backed.
    return IntegrationConnectionService(
        TenantRepository(session),
        IntegrationConnectionRepository(session),
        IntegrationSecretCipher(
            request.app.state.settings.integration_encryption_key.get_secret_value()
        ),
    )


Service = Annotated[IntegrationConnectionService, Depends(service)]


def http_error(error: IntegrationConnectionError) -> HTTPException:
    if str(error) in {"tenant_not_found", "connection_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def response(view: IntegrationConnectionView) -> IntegrationConnectionResponse:
    credential = view.credential
    return IntegrationConnectionResponse(
        id=view.connection.id,
        tenant_id=view.connection.tenant_id,
        key=view.connection.key,
        provider=view.connection.provider,
        config=view.connection.config,
        status=view.connection.status,
        revision=view.connection.revision,
        credential_version=credential.version if credential else None,
        credential_fingerprint=credential.fingerprint if credential else None,
        created_at=view.connection.created_at,
        updated_at=view.connection.updated_at,
    )


@router.post(
    "",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    tenant_id: UUID,
    data: CreateIntegrationConnectionRequest,
    connections: Service,
) -> IntegrationConnectionResponse:
    try:
        connection = await connections.create(tenant_id, data)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    return response(connection)


@router.get("", response_model=list[IntegrationConnectionResponse])
async def list_connections(
    tenant_id: UUID, connections: Service
) -> list[IntegrationConnectionResponse]:
    try:
        items = await connections.list(tenant_id)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    return [response(item) for item in items]


@router.patch("/{connection_id}", response_model=IntegrationConnectionResponse)
async def update_connection(
    tenant_id: UUID,
    connection_id: UUID,
    data: UpdateIntegrationConnectionRequest,
    connections: Service,
) -> IntegrationConnectionResponse:
    try:
        connection = await connections.update(tenant_id, connection_id, data)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    return response(connection)


@router.post("/{connection_id}/enable", response_model=IntegrationConnectionResponse)
async def enable_connection(
    tenant_id: UUID, connection_id: UUID, connections: Service
) -> IntegrationConnectionResponse:
    try:
        return response(
            await connections.update(
                tenant_id,
                connection_id,
                UpdateIntegrationConnectionRequest(
                    status=IntegrationConnectionStatus.ACTIVE
                ),
            )
        )
    except IntegrationConnectionError as error:
        raise http_error(error) from error


@router.post("/{connection_id}/disable", response_model=IntegrationConnectionResponse)
async def disable_connection(
    tenant_id: UUID, connection_id: UUID, connections: Service
) -> IntegrationConnectionResponse:
    try:
        return response(
            await connections.update(
                tenant_id,
                connection_id,
                UpdateIntegrationConnectionRequest(
                    status=IntegrationConnectionStatus.DISABLED
                ),
            )
        )
    except IntegrationConnectionError as error:
        raise http_error(error) from error


@router.post("/{connection_id}/secrets", response_model=IntegrationConnectionResponse)
async def set_secret(
    tenant_id: UUID,
    connection_id: UUID,
    data: SetIntegrationSecretRequest,
    connections: Service,
) -> IntegrationConnectionResponse:
    try:
        return response(
            await connections.set_secret(
                tenant_id, connection_id, data.secret, rotate=False
            )
        )
    except IntegrationConnectionError as error:
        raise http_error(error) from error


@router.post(
    "/{connection_id}/secrets/rotate", response_model=IntegrationConnectionResponse
)
async def rotate_secret(
    tenant_id: UUID,
    connection_id: UUID,
    data: SetIntegrationSecretRequest,
    connections: Service,
) -> IntegrationConnectionResponse:
    try:
        return response(
            await connections.set_secret(
                tenant_id, connection_id, data.secret, rotate=True
            )
        )
    except IntegrationConnectionError as error:
        raise http_error(error) from error


@router.delete("/{connection_id}/secrets", response_model=IntegrationConnectionResponse)
async def revoke_secret(
    tenant_id: UUID, connection_id: UUID, connections: Service
) -> IntegrationConnectionResponse:
    try:
        return response(await connections.revoke_secret(tenant_id, connection_id))
    except IntegrationConnectionError as error:
        raise http_error(error) from error


@router.post("/{connection_id}/test", response_model=IntegrationTestResponse)
async def test_connection(
    tenant_id: UUID, connection_id: UUID, connections: Service
) -> IntegrationTestResponse:
    try:
        view = await connections.test(tenant_id, connection_id)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    assert view.credential is not None
    return IntegrationTestResponse(
        integration_id=view.connection.id,
        status="ready",
        credential_version=view.credential.version,
    )


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    tenant_id: UUID,
    connection_id: UUID,
    connections: Service,
) -> Response:
    try:
        await connections.delete(tenant_id, connection_id)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
