from unittest.mock import AsyncMock

import pytest
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.repository import TenantRepository
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
    service = TenantService(repository)

    assert await service.get_by_slug("penzion-grand") is tenant

    repository.get_by_slug.return_value = None
    with pytest.raises(TenantNotFoundError):
        await service.get_by_slug("missing-tenant")
