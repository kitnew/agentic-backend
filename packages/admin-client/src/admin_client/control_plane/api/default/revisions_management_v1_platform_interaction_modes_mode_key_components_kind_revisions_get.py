from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_response import ErrorResponse
from ...models.versioned_component_revision_response import (
    VersionedComponentRevisionResponse,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    mode_key: str,
    kind: str,
    *,
    limit: int | Unset = 100,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/management/v1/platform/interaction-modes/{mode_key}/components/{kind}/revisions".format(
            mode_key=quote(str(mode_key), safe=""),
            kind=quote(str(kind), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorResponse | list[VersionedComponentRevisionResponse] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = VersionedComponentRevisionResponse.from_dict(
                response_200_item_data
            )

            response_200.append(response_200_item)

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
) -> Response[ErrorResponse | list[VersionedComponentRevisionResponse]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    mode_key: str,
    kind: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
) -> Response[ErrorResponse | list[VersionedComponentRevisionResponse]]:
    """Revisions

    Args:
        mode_key (str):
        kind (str):
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | list[VersionedComponentRevisionResponse]]
    """

    kwargs = _get_kwargs(
        mode_key=mode_key,
        kind=kind,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    mode_key: str,
    kind: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
) -> ErrorResponse | list[VersionedComponentRevisionResponse] | None:
    """Revisions

    Args:
        mode_key (str):
        kind (str):
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | list[VersionedComponentRevisionResponse]
    """

    return sync_detailed(
        mode_key=mode_key,
        kind=kind,
        client=client,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    mode_key: str,
    kind: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
) -> Response[ErrorResponse | list[VersionedComponentRevisionResponse]]:
    """Revisions

    Args:
        mode_key (str):
        kind (str):
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | list[VersionedComponentRevisionResponse]]
    """

    kwargs = _get_kwargs(
        mode_key=mode_key,
        kind=kind,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    mode_key: str,
    kind: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
) -> ErrorResponse | list[VersionedComponentRevisionResponse] | None:
    """Revisions

    Args:
        mode_key (str):
        kind (str):
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | list[VersionedComponentRevisionResponse]
    """

    return (
        await asyncio_detailed(
            mode_key=mode_key,
            kind=kind,
            client=client,
            limit=limit,
        )
    ).parsed
