from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    CreateIntegrationConnectionRequest,
    IntegrationConnectionResponse,
    UpdateIntegrationConnectionRequest,
)
from backend_core.modules.integrations.service import (
    IntegrationConnectionError,
    IntegrationConnectionService,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/integration-connections",
    tags=["admin:integrations"],
    dependencies=[Depends(require_admin)],
)


def service(session: DatabaseSession) -> IntegrationConnectionService:
    return IntegrationConnectionService(
        TenantRepository(session), IntegrationConnectionRepository(session)
    )


Service = Annotated[IntegrationConnectionService, Depends(service)]


def http_error(error: IntegrationConnectionError) -> HTTPException:
    if str(error) in {"tenant_not_found", "connection_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


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
    return IntegrationConnectionResponse.model_validate(connection)


@router.get("", response_model=list[IntegrationConnectionResponse])
async def list_connections(
    tenant_id: UUID, connections: Service
) -> list[IntegrationConnectionResponse]:
    try:
        items = await connections.list(tenant_id)
    except IntegrationConnectionError as error:
        raise http_error(error) from error
    return [IntegrationConnectionResponse.model_validate(item) for item in items]


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
    return IntegrationConnectionResponse.model_validate(connection)
