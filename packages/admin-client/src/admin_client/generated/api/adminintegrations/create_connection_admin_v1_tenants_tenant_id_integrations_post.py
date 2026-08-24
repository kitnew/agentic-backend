from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_integration_connection_request import (
    CreateIntegrationConnectionRequest,
)
from ...models.http_validation_error import HTTPValidationError
from ...models.integration_connection_response import IntegrationConnectionResponse
from ...types import Response


def _get_kwargs(
    tenant_id: UUID,
    *,
    body: CreateIntegrationConnectionRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/v1/tenants/{tenant_id}/integrations".format(
            tenant_id=quote(str(tenant_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    if response.status_code == 201:
        response_201 = IntegrationConnectionResponse.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: CreateIntegrationConnectionRequest,
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    """Create Connection

    Args:
        tenant_id (UUID):
        body (CreateIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IntegrationConnectionResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: CreateIntegrationConnectionRequest,
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    """Create Connection

    Args:
        tenant_id (UUID):
        body (CreateIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IntegrationConnectionResponse
    """

    return sync_detailed(
        tenant_id=tenant_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: CreateIntegrationConnectionRequest,
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    """Create Connection

    Args:
        tenant_id (UUID):
        body (CreateIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IntegrationConnectionResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: CreateIntegrationConnectionRequest,
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    """Create Connection

    Args:
        tenant_id (UUID):
        body (CreateIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IntegrationConnectionResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            client=client,
            body=body,
        )
    ).parsed
