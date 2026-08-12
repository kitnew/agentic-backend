from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.call_session_response import CallSessionResponse
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    call_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/v1/calls/{call_id}".format(
            call_id=quote(str(call_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CallSessionResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CallSessionResponse.from_dict(response.json())

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
) -> Response[CallSessionResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    call_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[CallSessionResponse | HTTPValidationError]:
    """Get Admin Call

    Args:
        call_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CallSessionResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        call_id=call_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    call_id: UUID,
    *,
    client: AuthenticatedClient,
) -> CallSessionResponse | HTTPValidationError | None:
    """Get Admin Call

    Args:
        call_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CallSessionResponse | HTTPValidationError
    """

    return sync_detailed(
        call_id=call_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    call_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[CallSessionResponse | HTTPValidationError]:
    """Get Admin Call

    Args:
        call_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CallSessionResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        call_id=call_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    call_id: UUID,
    *,
    client: AuthenticatedClient,
) -> CallSessionResponse | HTTPValidationError | None:
    """Get Admin Call

    Args:
        call_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CallSessionResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            call_id=call_id,
            client=client,
        )
    ).parsed
