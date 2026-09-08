from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from control_plane.application.platform_configuration import (
    ConfigurationStatus,
    PromptState,
)
from control_plane.application.tenant_configuration import (
    TenantConfiguration,
    TenantConfigurationApplyResult,
    TenantConfigurationChanges,
    TenantConfigurationPlan,
    TenantConfigurationPublishResult,
    TenantLiveConfiguration,
    TenantVersionedConfiguration,
)
from control_plane.domain.frozen_components import (
    ActionsAvailability,
    Architecture,
    ProfileReference,
    default_component_definition_registry,
)
from control_plane.domain.live_components import LiveComponentState
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


class Tenant:
    def __init__(self):
        self.value = TenantConfiguration(
            tenant_id="tenant-a",
            versioned=TenantVersionedConfiguration(
                tenant_prompt=PromptState(),
                knowledge=PromptState(),
                agent_personality=PromptState(),
                business_info=PromptState(),
                actions_definition=PromptState(),
            ),
            live=TenantLiveConfiguration(
                architecture=Architecture(architecture_key="cascade"),
                profile_reference=ProfileReference(profile_key="sales"),
                runtime_overrides={},
                actions_availability=ActionsAvailability(actions={}),
            ),
            status=ConfigurationStatus(has_drafts=False, publishable=False),
        )

    async def get(self, _tenant_id):
        return self.value

    async def plan(self, _tenant_id, _desired):
        return TenantConfigurationPlan(True, TenantConfigurationChanges((), ()), (), ())

    async def apply(self, _tenant_id, _desired, _token, _principal, _key):
        return TenantConfigurationApplyResult((), (), (), self.value)

    async def publish(self, _tenant_id, _token, _principal, _key):
        return TenantConfigurationPublishResult((), (), self.value)

    @staticmethod
    def concurrency_token(_value):
        return "aggregate"


def app():
    value = create_http_app(Lifecycle(), tenant_configuration=Tenant())
    value.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "secret"
        ),
        control_plane_management_actor="admin",
        control_plane_management_scopes="configuration:read,configuration:write",
    )
    return value


class Components:
    registry = default_component_definition_registry()

    def lifecycle(self, address):
        return self.registry.resolve(address).metadata["lifecycle"]


class Live:
    async def get(self, address):
        return LiveComponentState(
            address,
            Architecture(architecture_key="cascade"),
            1,
            1,
            datetime.now(UTC),
            "admin",
        )

    async def set(self, address, value, _token, principal, _key):
        return LiveComponentState(
            address,
            Architecture.model_validate(value),
            1,
            1,
            datetime.now(UTC),
            principal,
        )

    @staticmethod
    def concurrency_token(_value):
        return "live"


def component_app():
    value = create_http_app(
        Lifecycle(), components=Components(), tenant_live_components=Live()
    )
    value.state.settings = app().state.settings
    return value


def test_openapi_contains_only_frozen_tenant_configuration_methods() -> None:
    paths = app().openapi()["paths"]
    assert set(paths["/management/v1/tenants/{tenant_id}/configuration"]) == {
        "get",
        "put",
    }
    assert set(paths["/management/v1/tenants/{tenant_id}/configuration/plan"]) == {
        "post"
    }
    assert set(paths["/management/v1/tenants/{tenant_id}/configuration/publish"]) == {
        "post"
    }
    assert "/v1/scopes/tenant/{tenant_id}/components/{kind}" not in paths


@pytest.mark.asyncio
async def test_tenant_configuration_etag_and_command_headers() -> None:
    auth = {"Authorization": "Bearer secret"}
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        read = await client.get(
            "/management/v1/tenants/tenant-a/configuration", headers=auth
        )
        missing = await client.post(
            "/management/v1/tenants/tenant-a/configuration/publish", headers=auth
        )
        publish = await client.post(
            "/management/v1/tenants/tenant-a/configuration/publish",
            headers={
                **auth,
                "If-Match": '"aggregate"',
                "Idempotency-Key": "publish",
            },
        )
    assert read.status_code == 200 and read.headers["etag"] == '"aggregate"'
    assert missing.status_code == 400
    assert publish.status_code == 200 and publish.headers["etag"] == '"aggregate"'


@pytest.mark.asyncio
async def test_tenant_low_level_live_route_cannot_use_versioned_lifecycle() -> None:
    paths = component_app().openapi()["paths"]
    assert "put" in paths["/management/v1/tenants/{tenant_id}/components/{kind}"]
    assert "put" not in paths["/management/v1/platform/components/{kind}"]
    auth = {"Authorization": "Bearer secret"}
    base = "/management/v1/tenants/tenant-a/components/Architecture"
    async with AsyncClient(
        transport=ASGITransport(app=component_app()), base_url="http://test"
    ) as client:
        live = await client.put(
            base,
            headers={**auth, "If-Match": '"*"', "Idempotency-Key": "live"},
            json={"value": {"architecture_key": "cascade"}},
        )
        draft = await client.put(
            f"{base}/draft",
            headers={**auth, "If-Match": '"*"'},
            json={"value": {"architecture_key": "cascade"}},
        )
    assert live.status_code == 200 and live.headers["etag"] == '"live"'
    assert draft.status_code == 422
