from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.config_revision_response import ConfigRevisionResponse
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    tenant_id: UUID,
    revision_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/v1/tenants/{tenant_id}/config/drafts/{revision_id}/publish".format(
            tenant_id=quote(str(tenant_id), safe=""),
            revision_id=quote(str(revision_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ConfigRevisionResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = ConfigRevisionResponse.from_dict(response.json())

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
) -> Response[ConfigRevisionResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: UUID,
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ConfigRevisionResponse | HTTPValidationError]:
    """Publish Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ConfigRevisionResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        revision_id=revision_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ConfigRevisionResponse | HTTPValidationError | None:
    """Publish Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ConfigRevisionResponse | HTTPValidationError
    """

    return sync_detailed(
        tenant_id=tenant_id,
        revision_id=revision_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ConfigRevisionResponse | HTTPValidationError]:
    """Publish Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ConfigRevisionResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        revision_id=revision_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ConfigRevisionResponse | HTTPValidationError | None:
    """Publish Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ConfigRevisionResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            revision_id=revision_id,
            client=client,
        )
    ).parsed
