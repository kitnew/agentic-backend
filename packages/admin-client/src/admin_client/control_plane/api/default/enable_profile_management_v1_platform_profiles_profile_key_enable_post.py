from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.catalog_response import CatalogResponse
from ...models.error_response import ErrorResponse
from ...types import Response


def _get_kwargs(
    profile_key: str,
    *,
    idempotency_key: str,
    if_match: str,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers["Idempotency-Key"] = idempotency_key

    headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/management/v1/platform/profiles/{profile_key}/enable".format(
            profile_key=quote(str(profile_key), safe=""),
        ),
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CatalogResponse | ErrorResponse | None:
    if response.status_code == 200:
        response_200 = CatalogResponse.from_dict(response.json())

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
) -> Response[CatalogResponse | ErrorResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    profile_key: str,
    *,
    client: AuthenticatedClient,
    idempotency_key: str,
    if_match: str,
) -> Response[CatalogResponse | ErrorResponse]:
    """Enable Profile

    Args:
        profile_key (str):
        idempotency_key (str):
        if_match (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CatalogResponse | ErrorResponse]
    """

    kwargs = _get_kwargs(
        profile_key=profile_key,
        idempotency_key=idempotency_key,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    profile_key: str,
    *,
    client: AuthenticatedClient,
    idempotency_key: str,
    if_match: str,
) -> CatalogResponse | ErrorResponse | None:
    """Enable Profile

    Args:
        profile_key (str):
        idempotency_key (str):
        if_match (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CatalogResponse | ErrorResponse
    """

    return sync_detailed(
        profile_key=profile_key,
        client=client,
        idempotency_key=idempotency_key,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    profile_key: str,
    *,
    client: AuthenticatedClient,
    idempotency_key: str,
    if_match: str,
) -> Response[CatalogResponse | ErrorResponse]:
    """Enable Profile

    Args:
        profile_key (str):
        idempotency_key (str):
        if_match (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CatalogResponse | ErrorResponse]
    """

    kwargs = _get_kwargs(
        profile_key=profile_key,
        idempotency_key=idempotency_key,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    profile_key: str,
    *,
    client: AuthenticatedClient,
    idempotency_key: str,
    if_match: str,
) -> CatalogResponse | ErrorResponse | None:
    """Enable Profile

    Args:
        profile_key (str):
        idempotency_key (str):
        if_match (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CatalogResponse | ErrorResponse
    """

    return (
        await asyncio_detailed(
            profile_key=profile_key,
            client=client,
            idempotency_key=idempotency_key,
            if_match=if_match,
        )
    ).parsed
