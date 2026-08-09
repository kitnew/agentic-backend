from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.prompt_text_revision_response import PromptTextRevisionResponse
from ...models.update_text_draft_request import UpdateTextDraftRequest
from ...types import UNSET, Response, Unset


def _get_kwargs(
    revision_id: UUID,
    *,
    body: UpdateTextDraftRequest,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/admin/v1/platform/prompts/profiles/drafts/{revision_id}".format(
            revision_id=quote(str(revision_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PromptTextRevisionResponse | None:
    if response.status_code == 200:
        response_200 = PromptTextRevisionResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | PromptTextRevisionResponse]:
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
    body: UpdateTextDraftRequest,
    if_match: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | PromptTextRevisionResponse]:
    """Update Profile Prompt Draft

    Args:
        revision_id (UUID):
        if_match (None | str | Unset):
        body (UpdateTextDraftRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PromptTextRevisionResponse]
    """

    kwargs = _get_kwargs(
        revision_id=revision_id,
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateTextDraftRequest,
    if_match: None | str | Unset = UNSET,
) -> HTTPValidationError | PromptTextRevisionResponse | None:
    """Update Profile Prompt Draft

    Args:
        revision_id (UUID):
        if_match (None | str | Unset):
        body (UpdateTextDraftRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PromptTextRevisionResponse
    """

    return sync_detailed(
        revision_id=revision_id,
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateTextDraftRequest,
    if_match: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | PromptTextRevisionResponse]:
    """Update Profile Prompt Draft

    Args:
        revision_id (UUID):
        if_match (None | str | Unset):
        body (UpdateTextDraftRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PromptTextRevisionResponse]
    """

    kwargs = _get_kwargs(
        revision_id=revision_id,
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    revision_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UpdateTextDraftRequest,
    if_match: None | str | Unset = UNSET,
) -> HTTPValidationError | PromptTextRevisionResponse | None:
    """Update Profile Prompt Draft

    Args:
        revision_id (UUID):
        if_match (None | str | Unset):
        body (UpdateTextDraftRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PromptTextRevisionResponse
    """

    return (
        await asyncio_detailed(
            revision_id=revision_id,
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
