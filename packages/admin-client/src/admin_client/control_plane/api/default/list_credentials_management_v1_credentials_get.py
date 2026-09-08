from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.credential_response import CredentialResponse
from ...models.error_response import ErrorResponse
from ...models.list_credentials_management_v1_credentials_get_scope_type_type_0 import (
    ListCredentialsManagementV1CredentialsGetScopeTypeType0,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    scope_type: ListCredentialsManagementV1CredentialsGetScopeTypeType0
    | None
    | Unset = UNSET,
    tenant_id: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_scope_type: None | str | Unset
    if isinstance(scope_type, Unset):
        json_scope_type = UNSET
    elif isinstance(
        scope_type, ListCredentialsManagementV1CredentialsGetScopeTypeType0
    ):
        json_scope_type = scope_type.value
    else:
        json_scope_type = scope_type
    params["scope_type"] = json_scope_type

    json_tenant_id: None | str | Unset
    if isinstance(tenant_id, Unset):
        json_tenant_id = UNSET
    else:
        json_tenant_id = tenant_id
    params["tenant_id"] = json_tenant_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/management/v1/credentials",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorResponse | list[CredentialResponse] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = CredentialResponse.from_dict(response_200_item_data)

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
) -> Response[ErrorResponse | list[CredentialResponse]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    scope_type: ListCredentialsManagementV1CredentialsGetScopeTypeType0
    | None
    | Unset = UNSET,
    tenant_id: None | str | Unset = UNSET,
) -> Response[ErrorResponse | list[CredentialResponse]]:
    """List Credentials

    Args:
        scope_type (ListCredentialsManagementV1CredentialsGetScopeTypeType0 | None | Unset):
        tenant_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | list[CredentialResponse]]
    """

    kwargs = _get_kwargs(
        scope_type=scope_type,
        tenant_id=tenant_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    scope_type: ListCredentialsManagementV1CredentialsGetScopeTypeType0
    | None
    | Unset = UNSET,
    tenant_id: None | str | Unset = UNSET,
) -> ErrorResponse | list[CredentialResponse] | None:
    """List Credentials

    Args:
        scope_type (ListCredentialsManagementV1CredentialsGetScopeTypeType0 | None | Unset):
        tenant_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | list[CredentialResponse]
    """

    return sync_detailed(
        client=client,
        scope_type=scope_type,
        tenant_id=tenant_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    scope_type: ListCredentialsManagementV1CredentialsGetScopeTypeType0
    | None
    | Unset = UNSET,
    tenant_id: None | str | Unset = UNSET,
) -> Response[ErrorResponse | list[CredentialResponse]]:
    """List Credentials

    Args:
        scope_type (ListCredentialsManagementV1CredentialsGetScopeTypeType0 | None | Unset):
        tenant_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorResponse | list[CredentialResponse]]
    """

    kwargs = _get_kwargs(
        scope_type=scope_type,
        tenant_id=tenant_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    scope_type: ListCredentialsManagementV1CredentialsGetScopeTypeType0
    | None
    | Unset = UNSET,
    tenant_id: None | str | Unset = UNSET,
) -> ErrorResponse | list[CredentialResponse] | None:
    """List Credentials

    Args:
        scope_type (ListCredentialsManagementV1CredentialsGetScopeTypeType0 | None | Unset):
        tenant_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorResponse | list[CredentialResponse]
    """

    return (
        await asyncio_detailed(
            client=client,
            scope_type=scope_type,
            tenant_id=tenant_id,
        )
    ).parsed
