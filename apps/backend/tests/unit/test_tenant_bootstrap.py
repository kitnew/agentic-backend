from uuid import UUID

import pytest
from backend_core.modules.tenants.schemas import CreateTenantRequest
from backend_core.modules.tenants.service import TenantService


class Repository:
    async def get_by_slug(self, slug):
        return None

    async def add(self, tenant):
        tenant.id = UUID("11111111-1111-1111-1111-111111111111")
        return tenant


class Releases:
    def __init__(self):
        self.saved = []

    async def save_draft(self, **kwargs):
        self.saved.append(kwargs)


@pytest.mark.asyncio
async def test_new_tenant_bootstraps_all_local_authoring_drafts():
    releases = Releases()
    tenant = await TenantService(Repository(), releases).create(
        CreateTenantRequest(
            slug="hotel",
            display_name="Hotel",
            business_type="hotel",
        )
    )

    assert tenant.slug == "hotel"
    assert {item["component"].value for item in releases.saved} == {
        "agent",
        "runtime",
        "prompt",
        "knowledge",
        "capabilities",
        "post_call",
        "telephony",
    }
    agent = next(item["payload"] for item in releases.saved if item["component"].value == "agent")
    assert agent["business"] == {"name": "Hotel", "type": "hotel"}
    assert set(agent) == {"agent", "business", "contact", "localization", "conversation", "handoff"}
