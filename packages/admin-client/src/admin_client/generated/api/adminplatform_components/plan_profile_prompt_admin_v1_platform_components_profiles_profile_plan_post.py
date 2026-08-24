from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.authoring_plan import AuthoringPlan
from ...models.http_validation_error import HTTPValidationError
from ...models.prompt_draft_write import PromptDraftWrite
from ...types import Response


def _get_kwargs(
    profile: str,
    *,
    body: PromptDraftWrite,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/v1/platform/components/profiles/{profile}/plan".format(
            profile=quote(str(profile), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AuthoringPlan | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = AuthoringPlan.from_dict(response.json())

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
) -> Response[AuthoringPlan | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    profile: str,
    *,
    client: AuthenticatedClient,
    body: PromptDraftWrite,
) -> Response[AuthoringPlan | HTTPValidationError]:
    """Plan Profile Prompt

    Args:
        profile (str):
        body (PromptDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuthoringPlan | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        profile=profile,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    profile: str,
    *,
    client: AuthenticatedClient,
    body: PromptDraftWrite,
) -> AuthoringPlan | HTTPValidationError | None:
    """Plan Profile Prompt

    Args:
        profile (str):
        body (PromptDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuthoringPlan | HTTPValidationError
    """

    return sync_detailed(
        profile=profile,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    profile: str,
    *,
    client: AuthenticatedClient,
    body: PromptDraftWrite,
) -> Response[AuthoringPlan | HTTPValidationError]:
    """Plan Profile Prompt

    Args:
        profile (str):
        body (PromptDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuthoringPlan | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        profile=profile,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    profile: str,
    *,
    client: AuthenticatedClient,
    body: PromptDraftWrite,
) -> AuthoringPlan | HTTPValidationError | None:
    """Plan Profile Prompt

    Args:
        profile (str):
        body (PromptDraftWrite):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuthoringPlan | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            profile=profile,
            client=client,
            body=body,
        )
    ).parsed
