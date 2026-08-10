from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.prompt_set_plan_response import PromptSetPlanResponse
from ...models.prompt_set_resolution_error_response import (
    PromptSetResolutionErrorResponse,
)
from ...types import Response


def _get_kwargs(
    tenant_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/v1/tenants/{tenant_id}/prompt-set/plan".format(
            tenant_id=quote(str(tenant_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> PromptSetPlanResponse | PromptSetResolutionErrorResponse | None:
    if response.status_code == 200:
        response_200 = PromptSetPlanResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = PromptSetResolutionErrorResponse.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[PromptSetPlanResponse | PromptSetResolutionErrorResponse]:
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
) -> Response[PromptSetPlanResponse | PromptSetResolutionErrorResponse]:
    """Plan Prompt Set

    Args:
        tenant_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PromptSetPlanResponse | PromptSetResolutionErrorResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
) -> PromptSetPlanResponse | PromptSetResolutionErrorResponse | None:
    """Plan Prompt Set

    Args:
        tenant_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PromptSetPlanResponse | PromptSetResolutionErrorResponse
    """

    return sync_detailed(
        tenant_id=tenant_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[PromptSetPlanResponse | PromptSetResolutionErrorResponse]:
    """Plan Prompt Set

    Args:
        tenant_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PromptSetPlanResponse | PromptSetResolutionErrorResponse]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: UUID,
    *,
    client: AuthenticatedClient,
) -> PromptSetPlanResponse | PromptSetResolutionErrorResponse | None:
    """Plan Prompt Set

    Args:
        tenant_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PromptSetPlanResponse | PromptSetResolutionErrorResponse
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            client=client,
        )
    ).parsed
