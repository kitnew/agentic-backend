from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

import pytest
from control_plane.application.providers import ProviderService
from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import DeploymentKind
from control_plane.domain.registries import ProviderKindRegistry
from control_plane.interfaces.http.app import (
    ModelDeploymentCreate,
    ProviderConnectionCreate,
    create_http_app,
)
from pydantic import ValidationError


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app: Any):
        yield


def test_provider_registry_owns_closed_connection_config_validation() -> None:
    registry = ProviderKindRegistry()

    assert registry.validate_connection(
        "azure_openai", {"endpoint": "https://example.openai.azure.com"}
    )["endpoint"] == "https://example.openai.azure.com/"
    with pytest.raises(InvalidManagedResource):
        registry.validate_connection("elevenlabs", {"unknown": True})
    with pytest.raises(InvalidManagedResource, match="unknown provider kind"):
        registry.validate_connection("unknown", {})
    with pytest.raises(InvalidManagedResource):
        registry.validate_connection("azure_openai", {"endpoint": "not-a-url"})
    with pytest.raises(InvalidManagedResource):
        registry.validate_deployment(
            "elevenlabs", DeploymentKind.TTS, {"model_id": "flash", "extra": True}
        )


def test_target_create_dtos_use_explicit_lifecycle_and_capability_union() -> None:
    with pytest.raises(ValidationError, match="enabled"):
        ProviderConnectionCreate.model_validate(
            {
                "key": "azure-prod",
                "provider_kind": "azure_openai",
                "credential_ref": str(uuid4()),
                "connection_config": {
                    "endpoint": "https://example.openai.azure.com"
                },
                "enabled": True,
            }
        )

    value = ModelDeploymentCreate.model_validate(
        {
            "key": "chat-prod",
            "connection_ref": str(uuid4()),
            "deployment_kind": "llm",
            "deployment_config": {
                "deployment_name": "chat",
                "model": "gpt-5.6-terra",
                "api_version": "2025-01-01-preview",
            },
            "capabilities": {
                "kind": "llm",
                "supports_temperature": True,
                "supports_reasoning_effort": True,
            },
        }
    )
    assert value.capabilities.kind == "llm"
    with pytest.raises(ValidationError):
        ModelDeploymentCreate.model_validate(
            {
                **value.model_dump(),
                "capabilities": {
                    "kind": "llm",
                    "supports_temperature": "yes",
                    "supports_reasoning_effort": True,
                },
            }
        )


def test_target_provider_routes_replace_legacy_managed_resource_routes() -> None:
    app = create_http_app(
        cast(Any, Lifecycle()), providers=cast(ProviderService, object())
    )
    paths = app.openapi()["paths"]

    assert "/management/v1/providers/connections" in paths
    assert "/management/v1/providers/connections/{id}/validate" in paths
    assert "/management/v1/providers/deployments" in paths
    assert "/management/v1/providers/deployments/{id}/validate" in paths
    assert "/v1/managed-resources/provider-connections" not in paths
    assert "/v1/managed-resources/model-deployments" not in paths
    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["ProviderConnectionResponse"]["properties"]) == {
        "id",
        "key",
        "provider_kind",
        "credential_ref",
        "connection_config",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert set(schemas["ProviderConnectionUpdate"]["properties"]) == {
        "credential_ref",
        "connection_config",
    }
    assert set(schemas["ModelDeploymentResponse"]["properties"]) == {
        "id",
        "key",
        "connection_ref",
        "deployment_kind",
        "deployment_config",
        "capabilities",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert set(schemas["ModelDeploymentUpdate"]["properties"]) == {
        "connection_ref",
        "deployment_config",
        "capabilities",
    }
    for schema_name in ("ProviderConnectionResponse", "ModelDeploymentResponse"):
        assert schemas[schema_name]["properties"]["created_at"]["format"] == "date-time"
        assert schemas[schema_name]["properties"]["updated_at"]["format"] == "date-time"
