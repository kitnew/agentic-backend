from http import HTTPStatus
from typing import assert_type

from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    list_tenants_admin_v1_tenants_get,
)


def check_generated_types(client: AuthenticatedClient) -> None:
    response = list_tenants_admin_v1_tenants_get.sync_detailed(client=client)
    assert_type(response.status_code, HTTPStatus)
