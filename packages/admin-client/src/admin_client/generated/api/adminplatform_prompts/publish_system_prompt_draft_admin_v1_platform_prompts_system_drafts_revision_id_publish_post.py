from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.platform_prompt_publish_response import PlatformPromptPublishResponse
from ...types import Response


def _get_kwargs(
    revision_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/v1/platform/prompts/system/drafts/{revision_id}/publish".format(
            revision_id=quote(str(revision_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PlatformPromptPublishResponse | None:
    if response.status_code == 200:
        response_200 = PlatformPromptPublishResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | PlatformPromptPublishResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | PlatformPromptPublishResponse]:
    """Publish System Prompt Draft

    Args:
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PlatformPromptPublishResponse]
    """

    kwargs = _get_kwargs(
        revision_id=revision_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | PlatformPromptPublishResponse | None:
    """Publish System Prompt Draft

    Args:
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PlatformPromptPublishResponse
    """

    return sync_detailed(
        revision_id=revision_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | PlatformPromptPublishResponse]:
    """Publish System Prompt Draft

    Args:
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PlatformPromptPublishResponse]
    """

    kwargs = _get_kwargs(
        revision_id=revision_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | PlatformPromptPublishResponse | None:
    """Publish System Prompt Draft

    Args:
        revision_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PlatformPromptPublishResponse
    """

    return (
        await asyncio_detailed(
            revision_id=revision_id,
            client=client,
        )
    ).parsed
