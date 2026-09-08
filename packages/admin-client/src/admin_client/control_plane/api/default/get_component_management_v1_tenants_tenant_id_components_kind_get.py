from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_response import ErrorResponse
from ...models.live_component_response import LiveComponentResponse
from ...models.versioned_component_response import VersionedComponentResponse
from ...types import Response


def _get_kwargs(
    tenant_id: str,
    kind: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/management/v1/tenants/{tenant_id}/components/{kind}".format(
            tenant_id=quote(str(tenant_id), safe=""),
            kind=quote(str(kind), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorResponse | LiveComponentResponse | VersionedComponentResponse | None:
    if response.status_code == 200:

        def _parse_response_200(
            data: object,
        ) -> LiveComponentResponse | VersionedComponentResponse:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_0 = LiveComponentResponse.from_dict(data)

                return response_200_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            response_200_type_1 = VersionedComponentResponse.from_dict(data)

            return response_200_type_1

        response_200 = _parse_response_200(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ErrorResponse.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ErrorResponse.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ErrorResponse.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ErrorResponse.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = ErrorResponse.from_dict(response.json())

        return response_409

    if response.status_code == 412:
        response_412 = ErrorResponse.from_dict(response.json())

        return response_412

    if response.status_code == 422:
        response_422 = ErrorResponse.from_dict(response.json())

        return response_422

    if response.status_code == 429:
        response_429 = ErrorResponse.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ErrorResponse.from_dict(response.json())

        return response_500

    if response.status_code == 503:
        response_503 = ErrorResponse.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ErrorResponse | LiveComponentResponse | VersionedComponentResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: str,
    kind: str,
    *,
    client: AuthenticatedClient,
) -> Response[ErrorResponse | LiveComponentResponse | VersionedComponentResponse]:
    """Get Component

    Args:
        tenant_id (str):
        kind (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | LiveComponentResponse | VersionedComponentResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        kind=kind,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: str,
    kind: str,
    *,
    client: AuthenticatedClient,
) -> ErrorResponse | LiveComponentResponse | VersionedComponentResponse | None:
    """Get Component

    Args:
        tenant_id (str):
        kind (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | LiveComponentResponse | VersionedComponentResponse
    """

    return sync_detailed(
        tenant_id=tenant_id,
        kind=kind,
        client=client,
    ).parsed


async def asyncio_detailed(
    tenant_id: str,
    kind: str,
    *,
    client: AuthenticatedClient,
) -> Response[ErrorResponse | LiveComponentResponse | VersionedComponentResponse]:
    """Get Component

    Args:
        tenant_id (str):
        kind (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | LiveComponentResponse | VersionedComponentResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        kind=kind,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: str,
    kind: str,
    *,
    client: AuthenticatedClient,
) -> ErrorResponse | LiveComponentResponse | VersionedComponentResponse | None:
    """Get Component

    Args:
        tenant_id (str):
        kind (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | LiveComponentResponse | VersionedComponentResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            kind=kind,
            client=client,
        )
    ).parsed
