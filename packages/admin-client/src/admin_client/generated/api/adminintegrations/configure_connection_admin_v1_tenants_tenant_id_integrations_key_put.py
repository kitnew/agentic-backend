from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.configure_integration_connection_request import (
    ConfigureIntegrationConnectionRequest,
)
from ...models.http_validation_error import HTTPValidationError
from ...models.integration_connection_response import IntegrationConnectionResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    tenant_id: UUID,
    key: str,
    *,
    body: ConfigureIntegrationConnectionRequest,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/admin/v1/tenants/{tenant_id}/integrations/{key}".format(
            tenant_id=quote(str(tenant_id), safe=""),
            key=quote(str(key), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    if response.status_code == 200:
        response_200 = IntegrationConnectionResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient,
    body: ConfigureIntegrationConnectionRequest,
    if_match: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    """Configure Connection

    Args:
        tenant_id (UUID):
        key (str):
        if_match (None | str | Unset):
        body (ConfigureIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IntegrationConnectionResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        key=key,
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient,
    body: ConfigureIntegrationConnectionRequest,
    if_match: None | str | Unset = UNSET,
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    """Configure Connection

    Args:
        tenant_id (UUID):
        key (str):
        if_match (None | str | Unset):
        body (ConfigureIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IntegrationConnectionResponse
    """

    return sync_detailed(
        tenant_id=tenant_id,
        key=key,
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient,
    body: ConfigureIntegrationConnectionRequest,
    if_match: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | IntegrationConnectionResponse]:
    """Configure Connection

    Args:
        tenant_id (UUID):
        key (str):
        if_match (None | str | Unset):
        body (ConfigureIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IntegrationConnectionResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        key=key,
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient,
    body: ConfigureIntegrationConnectionRequest,
    if_match: None | str | Unset = UNSET,
) -> HTTPValidationError | IntegrationConnectionResponse | None:
    """Configure Connection

    Args:
        tenant_id (UUID):
        key (str):
        if_match (None | str | Unset):
        body (ConfigureIntegrationConnectionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IntegrationConnectionResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            key=key,
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
