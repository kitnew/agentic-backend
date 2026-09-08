from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_response import ErrorResponse
from ...models.system_configuration_apply_result import SystemConfigurationApplyResult
from ...models.system_configuration_desired import SystemConfigurationDesired
from ...types import Response


def _get_kwargs(
    *,
    body: SystemConfigurationDesired,
    if_match: str,
    idempotency_key: str,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers["If-Match"] = if_match

    headers["Idempotency-Key"] = idempotency_key

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/management/v1/system/configuration",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorResponse | SystemConfigurationApplyResult | None:
    if response.status_code == 200:
        response_200 = SystemConfigurationApplyResult.from_dict(response.json())

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
) -> Response[ErrorResponse | SystemConfigurationApplyResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: SystemConfigurationDesired,
    if_match: str,
    idempotency_key: str,
) -> Response[ErrorResponse | SystemConfigurationApplyResult]:
    """Apply System Configuration

    Args:
        if_match (str):
        idempotency_key (str):
        body (SystemConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | SystemConfigurationApplyResult]
    """

    kwargs = _get_kwargs(
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: SystemConfigurationDesired,
    if_match: str,
    idempotency_key: str,
) -> ErrorResponse | SystemConfigurationApplyResult | None:
    """Apply System Configuration

    Args:
        if_match (str):
        idempotency_key (str):
        body (SystemConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | SystemConfigurationApplyResult
    """

    return sync_detailed(
        client=client,
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SystemConfigurationDesired,
    if_match: str,
    idempotency_key: str,
) -> Response[ErrorResponse | SystemConfigurationApplyResult]:
    """Apply System Configuration

    Args:
        if_match (str):
        idempotency_key (str):
        body (SystemConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | SystemConfigurationApplyResult]
    """

    kwargs = _get_kwargs(
        body=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: SystemConfigurationDesired,
    if_match: str,
    idempotency_key: str,
) -> ErrorResponse | SystemConfigurationApplyResult | None:
    """Apply System Configuration

    Args:
        if_match (str):
        idempotency_key (str):
        body (SystemConfigurationDesired):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | SystemConfigurationApplyResult
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            if_match=if_match,
            idempotency_key=idempotency_key,
        )
    ).parsed
