from contextlib import asynccontextmanager
from json import dumps
from pathlib import Path
from types import SimpleNamespace

import pytest
from control_plane.domain.frozen_components import (
    default_component_definition_registry,
)
from control_plane.domain.registries import (
    ArchitectureRegistry,
    DeploymentKindRegistry,
    IntegrationKindRegistry,
    ProviderKindRegistry,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient

from scripts.export_control_plane_openapi import control_plane_openapi


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def management_app():
    service = object()
    app = create_http_app(
        Lifecycle(),  # type: ignore[arg-type]
        components=service,  # type: ignore[arg-type]
        credentials=service,  # type: ignore[arg-type]
        providers=service,  # type: ignore[arg-type]
        system_configuration=service,  # type: ignore[arg-type]
        live_components=service,  # type: ignore[arg-type]
        tenant_live_components=service,  # type: ignore[arg-type]
        platform_configuration=service,  # type: ignore[arg-type]
        platform_catalogs=service,  # type: ignore[arg-type]
        integrations=service,  # type: ignore[arg-type]
        telephony=service,  # type: ignore[arg-type]
        tenant_configuration=service,  # type: ignore[arg-type]
        component_registry=default_component_definition_registry(),
        architecture_registry=ArchitectureRegistry(),
        provider_registry=ProviderKindRegistry(),
        deployment_registry=DeploymentKindRegistry(),
        integration_registry=IntegrationKindRegistry(),
    )
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        ),
        control_plane_management_actor="operator",
        control_plane_management_scopes=(
            "configuration:read,configuration:write,configuration:publish,"
            "resources:read,resources:write,credentials:write,registries:read"
        ),
    )
    return app


def _operations(schema):
    return {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method in {"get", "post", "put", "delete", "patch"}
    }


def _component_operations(base: str) -> set[tuple[str, str]]:
    return {
        ("GET", base),
        ("GET", f"{base}/draft"),
        ("PUT", f"{base}/draft"),
        ("DELETE", f"{base}/draft"),
        ("GET", f"{base}/active"),
        ("GET", f"{base}/revisions"),
        ("GET", f"{base}/revisions/{{revision_number}}"),
        ("POST", f"{base}/publish"),
        ("POST", f"{base}/rollback"),
    }


def expected_management_operations() -> set[tuple[str, str]]:
    operations = {
        ("GET", "/management/v1/system/configuration"),
        ("POST", "/management/v1/system/configuration/plan"),
        ("PUT", "/management/v1/system/configuration"),
        ("GET", "/management/v1/platform/configuration"),
        ("POST", "/management/v1/platform/configuration/plan"),
        ("PUT", "/management/v1/platform/configuration"),
        ("POST", "/management/v1/platform/configuration/publish"),
        ("GET", "/management/v1/tenants/{tenant_id}/configuration"),
        ("POST", "/management/v1/tenants/{tenant_id}/configuration/plan"),
        ("PUT", "/management/v1/tenants/{tenant_id}/configuration"),
        ("POST", "/management/v1/tenants/{tenant_id}/configuration/publish"),
        ("GET", "/management/v1/system/components/{kind}"),
        ("PUT", "/management/v1/system/components/{kind}"),
        ("GET", "/management/v1/tenants/{tenant_id}/components/{kind}"),
        ("PUT", "/management/v1/tenants/{tenant_id}/components/{kind}"),
    }
    for base in (
        "/management/v1/platform/components/{kind}",
        "/management/v1/platform/profiles/{profile_key}/components/{kind}",
        "/management/v1/platform/interaction-modes/{mode_key}/components/{kind}",
        "/management/v1/tenants/{tenant_id}/components/{kind}",
    ):
        operations |= _component_operations(base)
    collections = {
        "/management/v1/platform/profiles": ("profile_key", True, False),
        "/management/v1/platform/interaction-modes": ("mode_key", True, False),
        "/management/v1/credentials": ("id", False, False),
        "/management/v1/providers/connections": ("id", True, True),
        "/management/v1/providers/deployments": ("id", True, True),
        "/management/v1/tenants/{tenant_id}/integrations": ("id", True, True),
        "/management/v1/tenants/{tenant_id}/telephony/phone-number-assignments": (
            "id",
            False,
            False,
        ),
        "/management/v1/tenants/{tenant_id}/telephony/handoff-destinations": (
            "id",
            True,
            False,
        ),
    }
    for collection, (identifier, update, validate) in collections.items():
        item = f"{collection}/{{{identifier}}}"
        operations |= {("GET", collection), ("POST", collection), ("GET", item)}
        if update:
            operations.add(("PUT", item))
        if collection != "/management/v1/credentials":
            operations |= {("POST", f"{item}/enable"), ("POST", f"{item}/disable")}
        if validate:
            operations.add(("POST", f"{item}/validate"))
    operations |= {
        ("POST", "/management/v1/credentials/{id}/rotate"),
        ("POST", "/management/v1/credentials/{id}/revoke"),
    }
    operations |= {
        ("GET", f"/management/v1/registries/{name}")
        for name in (
            "architectures",
            "components",
            "provider-kinds",
            "deployment-kinds",
            "integration-kinds",
        )
    }
    return operations


def test_complete_frozen_management_inventory_is_the_only_management_surface() -> None:
    schema = management_app().openapi()
    actual = {
        operation
        for operation in _operations(schema)
        if operation[1].startswith("/management/")
    }

    assert actual == expected_management_operations()
    assert not any(path.startswith("/v1/") for _, path in actual)


def test_exported_openapi_matches_the_complete_mounted_management_surface() -> None:
    mounted = management_app().openapi()
    exported = control_plane_openapi()

    assert _operations(exported) == _operations(mounted)
    assert exported["components"]["schemas"] == mounted["components"]["schemas"]


@pytest.mark.asyncio
async def test_management_protocol_validation_uses_the_shared_error_envelope() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=management_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/management/v1/credentials",
            headers={
                "Authorization": "Bearer management-secret",
                "Content-Type": "application/json",
            },
            content="{",
        )

    assert response.status_code == 400
    assert set(response.json()) == {"code", "message", "issues", "request_id"}
    assert set(response.json()["issues"][0]) == {"code", "path", "message"}


def test_management_openapi_uses_shared_errors_and_has_no_legacy_concurrency_or_actor() -> (
    None
):
    schema = management_app().openapi()
    serialized = dumps(schema)

    assert {"ErrorResponse", "ValidationIssue"} <= set(schema["components"]["schemas"])
    assert "expected_generation" not in serialized
    assert "expected_draft_version" not in serialized
    assert "expected_active_revision_id" not in serialized
    assert '"actor"' not in serialized
    for path, item in schema["paths"].items():
        if not path.startswith("/management/v1/"):
            continue
        for method, operation in item.items():
            if method in {"get", "post", "put", "delete", "patch"}:
                assert operation["security"] == [{"ManagementToken": []}]
    publish = schema["paths"]["/management/v1/platform/configuration/publish"]["post"]
    assert {parameter["name"] for parameter in publish["parameters"]} == {
        "Idempotency-Key",
        "If-Match",
    }
    plan = schema["paths"]["/management/v1/platform/configuration/plan"]["post"]
    assert "parameters" not in plan


@pytest.mark.asyncio
async def test_management_auth_is_separate_and_permissions_are_enforced() -> None:
    app = management_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/management/v1/registries/architectures")
        service_token = await client.get(
            "/management/v1/registries/architectures",
            headers={"Authorization": "Bearer service-jwt"},
        )
        app.state.settings.control_plane_management_scopes = "configuration:read"
        forbidden = await client.get(
            "/management/v1/registries/architectures",
            headers={"Authorization": "Bearer management-secret"},
        )

    assert missing.status_code == service_token.status_code == 401
    assert forbidden.status_code == 403
    assert missing.json()["code"] == "unauthenticated"
    assert forbidden.json()["code"] == "permission_denied"


def test_management_consumers_do_not_reference_retired_transport() -> None:
    root = Path(__file__).resolve().parents[4]
    files = [
        *Path(root / "apps/agentctl/src").rglob("*.py"),
        *Path(root / "apps/admin-web/src").rglob("*.ts"),
        *Path(root / "apps/admin-web/src").rglob("*.tsx"),
        root / "apps/admin-web/vite.config.ts",
        root / "apps/admin-web/nginx.conf.template",
    ]
    source = "\n".join(path.read_text() for path in files)

    assert "/v1/scopes" not in source
    assert "/v1/managed-resources" not in source
    assert "expected_generation" not in source
    assert "expected_draft_version" not in source
    assert "expected_active_revision_id" not in source
