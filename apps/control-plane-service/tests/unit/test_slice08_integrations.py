from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from control_plane.application.integrations import IntegrationService
from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import (
    IntegrationConnection,
    IntegrationConnectionRef,
)
from control_plane.domain.registries import IntegrationKindRegistry
from control_plane.interfaces.http.app import (
    IntegrationConnectionCreate,
    IntegrationConnectionUpdate,
    create_http_app,
)
from pydantic import ValidationError


class _Registry(IntegrationKindRegistry):
    def __init__(self, transaction):
        self.transaction = transaction

    def validate_config(
        self, integration_kind: str, value: object
    ) -> dict[str, object]:
        assert not self.transaction.active
        return super().validate_config(integration_kind, value)


def test_integration_registry_accepts_known_kinds_and_validates_config() -> None:
    registry = IntegrationKindRegistry()
    assert (
        registry.validate_config(
            "http",
            {"endpoint": "https://example.com", "authentication": {"type": "none"}},
        )["endpoint"]
        == "https://example.com"
    )
    for kind in ("webhook", "pms", "unknown"):
        with pytest.raises(InvalidManagedResource, match="unknown integration"):
            registry.validate_config(kind, {})
    with pytest.raises(InvalidManagedResource):
        registry.validate_config("http", {"unknown": True})


def test_tenant_path_owns_identity_and_update_cannot_change_it() -> None:
    created = IntegrationConnectionCreate.model_validate(
        {
            "key": "booking-api",
            "integration_kind": "http",
            "config": {
                "endpoint": "https://example.com",
                "authentication": {"type": "none"},
            },
            "credential_ref": None,
        }
    )
    assert created.key == "booking-api"
    with pytest.raises(ValidationError):
        IntegrationConnectionCreate.model_validate(
            {
                "tenant_id": "tenant-b",
                "key": "booking-api",
                "integration_kind": "http",
                "config": {
                    "endpoint": "https://example.com",
                    "authentication": {"type": "none"},
                },
            }
        )
    for field, value in (
        ("tenant_id", "tenant-b"),
        ("key", "other"),
        ("integration_kind", "http"),
        ("enabled", True),
    ):
        with pytest.raises(ValidationError):
            IntegrationConnectionUpdate.model_validate(
                {"config": {}, "credential_ref": None, field: value}
            )


@pytest.mark.asyncio
async def test_validation_runs_kind_check_after_read_transaction_closes() -> None:
    now = datetime.now(UTC)
    connection = IntegrationConnection(
        IntegrationConnectionRef(uuid4()),
        "tenant-a",
        "booking",
        "http",
        {
            "endpoint": "https://example.com",
            "authentication": {"type": "none"},
        },
        None,
        False,
        1,
        now,
        "alice",
        now,
        "alice",
    )
    repository = SimpleNamespace(get=lambda _ref: _async_value(connection))
    transaction = SimpleNamespace(active=False)

    @asynccontextmanager
    async def scope():
        transaction.active = True
        try:
            yield repository, object()
        finally:
            transaction.active = False

    result = await IntegrationService(scope, _Registry(transaction)).validate(
        "tenant-a", connection.ref
    )
    assert result.valid is True
    assert result.usable is False


async def _async_value(value):
    return value


class _Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def test_openapi_exposes_only_target_integration_routes_and_dtos() -> None:
    schema = create_http_app(
        cast(Any, _Lifecycle()), integrations=cast(Any, object())
    ).openapi()
    paths = schema["paths"]
    collection = "/management/v1/tenants/{tenant_id}/integrations"
    resource = f"{collection}/{{id}}"
    assert set(paths[collection]) == {"get", "post"}
    assert set(paths[resource]) == {"get", "put"}
    assert f"{resource}/enable" in paths
    assert f"{resource}/disable" in paths
    assert f"{resource}/validate" in paths
    assert "/v1/managed-resources/integration-connections" not in paths
    schemas = schema["components"]["schemas"]
    assert set(schemas["IntegrationConnectionCreate"]["properties"]) == {
        "key",
        "integration_kind",
        "config",
        "credential_ref",
    }
    assert set(schemas["IntegrationConnectionUpdate"]["properties"]) == {
        "config",
        "credential_ref",
    }
