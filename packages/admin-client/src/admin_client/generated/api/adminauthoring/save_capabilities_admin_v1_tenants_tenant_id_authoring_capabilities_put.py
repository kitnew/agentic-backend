from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.authoring_state import AuthoringState
from ...models.http_validation_error import HTTPValidationError
from ...models.tenant_capabilities_authoring import TenantCapabilitiesAuthoring
from ...types import UNSET, Response, Unset


def _get_kwargs(
    tenant_id: UUID,
    *,
    body: TenantCapabilitiesAuthoring,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/admin/v1/tenants/{tenant_id}/authoring/capabilities".format(
            tenant_id=quote(str(tenant_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AuthoringState | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = AuthoringState.from_dict(response.json())

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
) -> Response[AuthoringState | HTTPValidationError]:
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
    body: TenantCapabilitiesAuthoring,
    if_match: None | str | Unset = UNSET,
) -> Response[AuthoringState | HTTPValidationError]:
    """Save Capabilities

    Args:
        tenant_id (UUID):
        if_match (None | str | Unset):
        body (TenantCapabilitiesAuthoring):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuthoringState | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: TenantCapabilitiesAuthoring,
    if_match: None | str | Unset = UNSET,
) -> AuthoringState | HTTPValidationError | None:
    """Save Capabilities

    Args:
        tenant_id (UUID):
        if_match (None | str | Unset):
        body (TenantCapabilitiesAuthoring):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuthoringState | HTTPValidationError
    """

    return sync_detailed(
        tenant_id=tenant_id,
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: TenantCapabilitiesAuthoring,
    if_match: None | str | Unset = UNSET,
) -> Response[AuthoringState | HTTPValidationError]:
    """Save Capabilities

    Args:
        tenant_id (UUID):
        if_match (None | str | Unset):
        body (TenantCapabilitiesAuthoring):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuthoringState | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
    body: TenantCapabilitiesAuthoring,
    if_match: None | str | Unset = UNSET,
) -> AuthoringState | HTTPValidationError | None:
    """Save Capabilities

    Args:
        tenant_id (UUID):
        if_match (None | str | Unset):
        body (TenantCapabilitiesAuthoring):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuthoringState | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
