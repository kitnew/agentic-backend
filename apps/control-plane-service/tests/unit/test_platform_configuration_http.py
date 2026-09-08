from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from control_plane.application.platform_configuration import (
    ConfigurationStatus,
    PlatformConfiguration,
    PlatformConfigurationApplyResult,
    PlatformConfigurationPlan,
    PlatformConfigurationPublishResult,
    PromptState,
)
from control_plane.domain.catalogs import CatalogStatus, Profile
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


class Platform:
    def __init__(self):
        self.value = PlatformConfiguration(
            system_prompt=PromptState(),
            profiles=(),
            interaction_modes=(),
            status=ConfigurationStatus(has_drafts=False, publishable=False),
        )

    async def get(self):
        return self.value

    async def plan(self, _desired):
        return PlatformConfigurationPlan(True, (), (), (), ())

    async def apply(self, _desired, _token, _principal, _key):
        return PlatformConfigurationApplyResult((), (), (), self.value)

    async def publish(self, _token, _principal, _key):
        return PlatformConfigurationPublishResult((), (), self.value)

    @staticmethod
    def concurrency_token(_value):
        return "aggregate"


class Catalogs:
    def __init__(self):
        now = datetime.now(UTC)
        self.profile = Profile(
            "sales", "Sales", "Sales profile", CatalogStatus.ENABLED, 1, now, now
        )

    async def list_profiles(self):
        return (self.profile,)

    async def get_profile(self, _key):
        return self.profile

    async def create_profile(self, _body, _principal, _key):
        return self.profile

    async def update_profile(self, _key, _body, _token, _principal, _idempotency):
        return self.profile

    async def set_profile_enabled(
        self, _key, _enabled, _token, _principal, _idempotency
    ):
        return self.profile

    @staticmethod
    def concurrency_token(_value):
        return "profile"


def app():
    value = create_http_app(
        Lifecycle(),
        components=object(),
        platform_configuration=Platform(),
        platform_catalogs=Catalogs(),
    )
    value.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "secret"
        ),
        control_plane_management_actor="admin",
        control_plane_management_scopes=(
            "configuration:read,configuration:write,configuration:publish"
        ),
    )
    return value


def test_openapi_contains_slice_07_routes() -> None:
    paths = app().openapi()["paths"]
    assert set(paths["/management/v1/platform/configuration"]) == {"get", "put"}
    assert set(paths["/management/v1/platform/configuration/plan"]) == {"post"}
    assert set(paths["/management/v1/platform/configuration/publish"]) == {"post"}
    assert set(paths["/management/v1/platform/profiles"]) == {"get", "post"}
    assert set(paths["/management/v1/platform/profiles/{profile_key}"]) == {
        "get",
        "put",
    }
    assert set(paths["/management/v1/platform/profiles/{profile_key}/enable"]) == {
        "post"
    }
    assert "/management/v1/platform/interaction-modes/{mode_key}/disable" in paths
    assert "/management/v1/platform/components/{kind}" in paths
    assert "/management/v1/platform/profiles/{profile_key}/components/{kind}" in paths
    assert (
        "/management/v1/platform/interaction-modes/{mode_key}/components/{kind}"
        in paths
    )


@pytest.mark.asyncio
async def test_platform_etags_and_command_headers() -> None:
    auth = {"Authorization": "Bearer secret"}
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        configuration = await client.get(
            "/management/v1/platform/configuration", headers=auth
        )
        profile = await client.get(
            "/management/v1/platform/profiles/sales", headers=auth
        )
        missing = await client.post(
            "/management/v1/platform/configuration/publish", headers=auth
        )
        published = await client.post(
            "/management/v1/platform/configuration/publish",
            headers={
                **auth,
                "If-Match": '"aggregate"',
                "Idempotency-Key": "publish",
            },
        )

    assert configuration.status_code == 200
    assert configuration.headers["etag"] == '"aggregate"'
    assert profile.status_code == 200 and profile.headers["etag"] == '"profile"'
    assert set(profile.json()) == {
        "key",
        "name",
        "description",
        "status",
        "created_at",
        "updated_at",
    }
    assert missing.status_code == 400
    assert published.status_code == 200
