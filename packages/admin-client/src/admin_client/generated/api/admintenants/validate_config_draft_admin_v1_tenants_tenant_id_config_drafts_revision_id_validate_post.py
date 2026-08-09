from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.validate_draft_response import ValidateDraftResponse
from ...types import Response


def _get_kwargs(
    tenant_id: UUID,
    revision_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/v1/tenants/{tenant_id}/config/drafts/{revision_id}/validate".format(
            tenant_id=quote(str(tenant_id), safe=""),
            revision_id=quote(str(revision_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ValidateDraftResponse | None:
    if response.status_code == 200:
        response_200 = ValidateDraftResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | ValidateDraftResponse]:
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
) -> Response[HTTPValidationError | ValidateDraftResponse]:
    """Validate Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ValidateDraftResponse]
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
) -> HTTPValidationError | ValidateDraftResponse | None:
    """Validate Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ValidateDraftResponse
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
) -> Response[HTTPValidationError | ValidateDraftResponse]:
    """Validate Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ValidateDraftResponse]
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
) -> HTTPValidationError | ValidateDraftResponse | None:
    """Validate Config Draft

    Args:
        tenant_id (UUID):
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ValidateDraftResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            revision_id=revision_id,
            client=client,
        )
    ).parsed
