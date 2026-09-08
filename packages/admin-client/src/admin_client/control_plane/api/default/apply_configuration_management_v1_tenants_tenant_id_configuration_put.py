from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_response import ErrorResponse
from ...models.tenant_configuration_apply_result import TenantConfigurationApplyResult
from ...models.tenant_configuration_desired import TenantConfigurationDesired
from ...types import UNSET, Response, Unset


def _get_kwargs(
    tenant_id: str,
    *,
    body: TenantConfigurationDesired,
    if_match: str | Unset = UNSET,
    idempotency_key: str,
    if_none_match: str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    headers["Idempotency-Key"] = idempotency_key

    if not isinstance(if_none_match, Unset):
        headers["If-None-Match"] = if_none_match

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/management/v1/tenants/{tenant_id}/configuration".format(
            tenant_id=quote(str(tenant_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorResponse | TenantConfigurationApplyResult | None:
    if response.status_code == 200:
        response_200 = TenantConfigurationApplyResult.from_dict(response.json())

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

    if response.status_code == 428:
        response_428 = ErrorResponse.from_dict(response.json())

        return response_428

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
) -> Response[ErrorResponse | TenantConfigurationApplyResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    tenant_id: str,
    *,
    client: AuthenticatedClient,
    body: TenantConfigurationDesired,
    if_match: str | Unset = UNSET,
    idempotency_key: str,
    if_none_match: str | Unset = UNSET,
) -> Response[ErrorResponse | TenantConfigurationApplyResult]:
    """Apply Configuration

    Args:
        tenant_id (str):
        if_match (str | Unset):
        idempotency_key (str):
        if_none_match (str | Unset):
        body (TenantConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | TenantConfigurationApplyResult]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
        if_none_match=if_none_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    tenant_id: str,
    *,
    client: AuthenticatedClient,
    body: TenantConfigurationDesired,
    if_match: str | Unset = UNSET,
    idempotency_key: str,
    if_none_match: str | Unset = UNSET,
) -> ErrorResponse | TenantConfigurationApplyResult | None:
    """Apply Configuration

    Args:
        tenant_id (str):
        if_match (str | Unset):
        idempotency_key (str):
        if_none_match (str | Unset):
        body (TenantConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | TenantConfigurationApplyResult
    """

    return sync_detailed(
        tenant_id=tenant_id,
        client=client,
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
        if_none_match=if_none_match,
    ).parsed


async def asyncio_detailed(
    tenant_id: str,
    *,
    client: AuthenticatedClient,
    body: TenantConfigurationDesired,
    if_match: str | Unset = UNSET,
    idempotency_key: str,
    if_none_match: str | Unset = UNSET,
) -> Response[ErrorResponse | TenantConfigurationApplyResult]:
    """Apply Configuration

    Args:
        tenant_id (str):
        if_match (str | Unset):
        idempotency_key (str):
        if_none_match (str | Unset):
        body (TenantConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | TenantConfigurationApplyResult]
    """

    kwargs = _get_kwargs(
        tenant_id=tenant_id,
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
        if_none_match=if_none_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    tenant_id: str,
    *,
    client: AuthenticatedClient,
    body: TenantConfigurationDesired,
    if_match: str | Unset = UNSET,
    idempotency_key: str,
    if_none_match: str | Unset = UNSET,
) -> ErrorResponse | TenantConfigurationApplyResult | None:
    """Apply Configuration

    Args:
        tenant_id (str):
        if_match (str | Unset):
        idempotency_key (str):
        if_none_match (str | Unset):
        body (TenantConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | TenantConfigurationApplyResult
    """

    return (
        await asyncio_detailed(
            tenant_id=tenant_id,
            client=client,
            body=body,
            if_match=if_match,
            idempotency_key=idempotency_key,
            if_none_match=if_none_match,
        )
    ).parsed
