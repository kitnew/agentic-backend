from unittest.mock import AsyncMock

import pytest
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.release_repository import (
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.modules.tenants.schemas import CreateTenantRequest
from backend_core.modules.tenants.service import TenantService


@pytest.mark.asyncio
async def test_tenant_lookup_by_slug() -> None:
    repository = AsyncMock(spec=TenantRepository)
    tenant = Tenant(
        slug="penzion-grand",
        display_name="Penzion Grand",
        business_type="hotel",
    )
    repository.get_by_slug.return_value = tenant
    service = TenantService(repository, AsyncMock(spec=TenantReleaseRepository))

    assert await service.get_by_slug("penzion-grand") is tenant

    repository.get_by_slug.return_value = None
    with pytest.raises(TenantNotFoundError):
        await service.get_by_slug("missing-tenant")


@pytest.mark.asyncio
async def test_new_tenant_starts_with_only_optional_component_drafts() -> None:
    tenants = AsyncMock(spec=TenantRepository)
    components = AsyncMock(spec=TenantReleaseRepository)
    tenant = Tenant(
        slug="new-hotel",
        display_name="New Hotel",
        business_type="hotel",
    )
    tenants.add.return_value = tenant
    tenants.get_by_slug.return_value = None
    service = TenantService(tenants, components)

    created = await service.create(
        CreateTenantRequest(
            slug="new-hotel", display_name="New Hotel", business_type="hotel"
        )
    )

    assert created.active_release_id is None
    assert [
        call.kwargs["component"] for call in components.save_draft.await_args_list
    ] == [
        TenantComponent.RUNTIME,
        TenantComponent.PROMPT,
        TenantComponent.KNOWLEDGE,
        TenantComponent.CAPABILITIES,
        TenantComponent.TELEPHONY,
    ]
