from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.draft_response import DraftResponse
from ...models.http_validation_error import HTTPValidationError
from ...models.runtime_draft_write import RuntimeDraftWrite
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: RuntimeDraftWrite,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/admin/v1/platform/components/runtime/draft",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DraftResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = DraftResponse.from_dict(response.json())

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
) -> Response[DraftResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: RuntimeDraftWrite,
    if_match: None | str | Unset = UNSET,
) -> Response[DraftResponse | HTTPValidationError]:
    """Save Runtime

    Args:
        if_match (None | str | Unset):
        body (RuntimeDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: RuntimeDraftWrite,
    if_match: None | str | Unset = UNSET,
) -> DraftResponse | HTTPValidationError | None:
    """Save Runtime

    Args:
        if_match (None | str | Unset):
        body (RuntimeDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: RuntimeDraftWrite,
    if_match: None | str | Unset = UNSET,
) -> Response[DraftResponse | HTTPValidationError]:
    """Save Runtime

    Args:
        if_match (None | str | Unset):
        body (RuntimeDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: RuntimeDraftWrite,
    if_match: None | str | Unset = UNSET,
) -> DraftResponse | HTTPValidationError | None:
    """Save Runtime

    Args:
        if_match (None | str | Unset):
        body (RuntimeDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
