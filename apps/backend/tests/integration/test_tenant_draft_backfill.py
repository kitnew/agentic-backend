from uuid import uuid4

import pytest
from backend_core.modules.tenants.defaults import backfill_missing_component_drafts
from backend_core.modules.tenants.release_repository import (
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.modules.tenants.schemas import CreateTenantRequest
from backend_core.modules.tenants.service import TenantService
from backend_core.platform.database import Database
from sqlalchemy import text

COMPONENTS = (
    "runtime",
    "prompt",
    "knowledge",
    "capabilities",
    "post_call",
    "telephony",
)


@pytest.mark.asyncio
async def test_backfill_restores_missing_agent_without_release_or_other_changes(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.transaction() as session:
            tenant = await TenantService(
                TenantRepository(session), TenantReleaseRepository(session)
            ).create(
                CreateTenantRequest(
                    slug=f"backfill-{uuid4().hex[:8]}",
                    display_name="Backfill Hotel",
                    business_type="hotel",
                )
            )
            releases = TenantReleaseRepository(session)
            before = {
                component: (await releases.draft(TenantComponent(component), tenant.id)).payload
                for component in COMPONENTS
            }
            await session.execute(
                text("DELETE FROM tenant_agent_drafts WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant.id},
            )
            await session.run_sync(
                lambda sync_session: backfill_missing_component_drafts(
                    sync_session.connection()
                )
            )
            agent = await releases.draft(TenantComponent.AGENT, tenant.id)
            assert agent is not None
            assert agent.payload["agent"]["display_name"] == "Backfill Hotel"
            for component, payload in before.items():
                current = await releases.draft(TenantComponent(component), tenant.id)
                assert current is not None
                assert current.payload == payload
            assert await releases.active_release(tenant.id) is None
    finally:
        await database.close()
