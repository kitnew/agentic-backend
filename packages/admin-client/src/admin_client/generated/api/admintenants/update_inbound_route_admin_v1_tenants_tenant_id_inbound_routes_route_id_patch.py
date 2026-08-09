from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.inbound_route_response import InboundRouteResponse
from ...models.update_inbound_route_request import UpdateInboundRouteRequest
from ...types import Response


def _get_kwargs(
    tenant_id: UUID,
    route_id: UUID,
    *,
    body: UpdateInboundRouteRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/admin/v1/tenants/{tenant_id}/inbound-routes/{route_id}".format(
            tenant_id=quote(str(tenant_id), safe=""),
            route_id=quote(str(route_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InboundRouteResponse | None:
    if response.status_code == 200:
        response_200 = InboundRouteResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | InboundRouteResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: UUID,
    route_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateInboundRouteRequest,
) -> Response[HTTPValidationError | InboundRouteResponse]:
    """Update Inbound Route

    Args:
        tenant_id (UUID):
        route_id (UUID):
        body (UpdateInboundRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InboundRouteResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        route_id=route_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    route_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateInboundRouteRequest,
) -> HTTPValidationError | InboundRouteResponse | None:
    """Update Inbound Route

    Args:
        tenant_id (UUID):
        route_id (UUID):
        body (UpdateInboundRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InboundRouteResponse
    """

    return sync_detailed(
        tenant_id=tenant_id,
        route_id=route_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    route_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateInboundRouteRequest,
) -> Response[HTTPValidationError | InboundRouteResponse]:
    """Update Inbound Route

    Args:
        tenant_id (UUID):
        route_id (UUID):
        body (UpdateInboundRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InboundRouteResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        route_id=route_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    route_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateInboundRouteRequest,
) -> HTTPValidationError | InboundRouteResponse | None:
    """Update Inbound Route

    Args:
        tenant_id (UUID):
        route_id (UUID):
        body (UpdateInboundRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InboundRouteResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            route_id=route_id,
            client=client,
            body=body,
        )
    ).parsed
