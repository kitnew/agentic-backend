from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    ConfigureIntegrationConnectionRequest,
    CreateIntegrationConnectionRequest,
    IntegrationConnectionResponse,
    IntegrationCredentialWrite,
    IntegrationPlan,
    IntegrationValidateResponse,
)
from backend_core.modules.integrations.service import (
    IntegrationConnectionError,
    IntegrationConnectionService,
    IntegrationConnectionView,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(prefix="/admin/v1/tenants/{tenant_id}/integrations", tags=["admin:integrations"], dependencies=[Depends(require_admin)])


def service(session: DatabaseSession, request: Request) -> IntegrationConnectionService:
    return IntegrationConnectionService(TenantRepository(session), IntegrationConnectionRepository(session), IntegrationSecretCipher(request.app.state.settings.integration_encryption_key.get_secret_value()))


Service = Annotated[IntegrationConnectionService, Depends(service)]


def _error(error: IntegrationConnectionError) -> HTTPException:
    code = str(error)
    status_code = status.HTTP_404_NOT_FOUND if code in {"tenant_not_found", "integration_not_found"} else status.HTTP_412_PRECONDITION_FAILED if code == "integration_conflict" else status.HTTP_409_CONFLICT
    return HTTPException(status_code, {"code": code, "message": code})


def _revision(value: str | None) -> int:
    if value is None or len(value) < 3 or value[0] != '"' or value[-1] != '"' or not value[1:-1].isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "invalid_etag", "message": "If-Match must be a quoted revision"})
    return int(value[1:-1])


def _response(view: IntegrationConnectionView) -> IntegrationConnectionResponse:
    credential = view.credential
    return IntegrationConnectionResponse(id=view.connection.id, tenant_id=view.connection.tenant_id, key=view.connection.key, kind=view.connection.kind, configuration=view.connection.configuration, enabled=view.connection.enabled, revision=view.connection.revision, credential_version=credential.version if credential and credential.status.value == "active" else None, credential_fingerprint=credential.fingerprint if credential else None, credential_status=None if credential is None else credential.status.value, readiness=view.readiness, created_at=view.connection.created_at, updated_at=view.connection.updated_at)


@router.post("", response_model=IntegrationConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(tenant_id: UUID, data: CreateIntegrationConnectionRequest, connections: Service) -> IntegrationConnectionResponse:
    try:
        return _response(await connections.create(tenant_id, data))
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.get("", response_model=list[IntegrationConnectionResponse])
async def list_connections(tenant_id: UUID, connections: Service) -> list[IntegrationConnectionResponse]:
    try:
        return [_response(item) for item in await connections.list(tenant_id)]
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.get("/{key}", response_model=IntegrationConnectionResponse)
async def get_connection(
    tenant_id: UUID,
    key: str,
    connections: Service,
    response: Response,
) -> IntegrationConnectionResponse:
    try:
        view = await connections.get(tenant_id, key)
    except IntegrationConnectionError as error:
        raise _error(error) from error
    response.headers["ETag"] = f'"{view.connection.revision}"'
    return _response(view)


@router.put("/{key}", response_model=IntegrationConnectionResponse)
async def configure_connection(tenant_id: UUID, key: str, data: ConfigureIntegrationConnectionRequest, connections: Service, response: Response, if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> IntegrationConnectionResponse:
    try:
        view = await connections.configure(tenant_id, key, data, _revision(if_match))
    except IntegrationConnectionError as error:
        raise _error(error) from error
    response.headers["ETag"] = f'"{view.connection.revision}"'
    return _response(view)


@router.post("/{key}/plan", response_model=IntegrationPlan)
async def plan_connection(tenant_id: UUID, key: str, data: ConfigureIntegrationConnectionRequest, connections: Service) -> IntegrationPlan:
    try:
        return await connections.plan(tenant_id, key, data)
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.post("/{key}/validate", response_model=IntegrationValidateResponse)
async def validate_connection(tenant_id: UUID, key: str, connections: Service) -> IntegrationValidateResponse:
    try:
        return (await connections.get(tenant_id, key)).readiness
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.post("/{key}/enable", response_model=IntegrationConnectionResponse)
async def enable_connection(tenant_id: UUID, key: str, connections: Service) -> IntegrationConnectionResponse:
    try:
        return _response(await connections.set_enabled(tenant_id, key, True))
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.post("/{key}/disable", response_model=IntegrationConnectionResponse)
async def disable_connection(tenant_id: UUID, key: str, connections: Service) -> IntegrationConnectionResponse:
    try:
        return _response(await connections.set_enabled(tenant_id, key, False))
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.post("/{key}/credentials/rotate", response_model=IntegrationConnectionResponse)
async def rotate_credential(tenant_id: UUID, key: str, data: IntegrationCredentialWrite, connections: Service) -> IntegrationConnectionResponse:
    try:
        return _response(await connections.rotate(tenant_id, key, data.api_key))
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.post("/{key}/credentials/revoke", response_model=IntegrationConnectionResponse)
async def revoke_credential(tenant_id: UUID, key: str, connections: Service) -> IntegrationConnectionResponse:
    try:
        return _response(await connections.revoke(tenant_id, key))
    except IntegrationConnectionError as error:
        raise _error(error) from error


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(tenant_id: UUID, key: str, connections: Service) -> Response:
    try:
        await connections.delete(tenant_id, key)
    except IntegrationConnectionError as error:
        raise _error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
