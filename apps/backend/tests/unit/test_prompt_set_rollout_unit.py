from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from backend_core.modules.tenants.errors import PromptSetResolutionError
from backend_core.modules.tenants.models import PromptSetRevision, Tenant
from backend_core.modules.tenants.service import PromptCompositionUseCases


def active_prompt_set(tenant: Tenant) -> PromptSetRevision:
    return PromptSetRevision(
        id=tenant.active_prompt_set_revision_id,
        prompt_set_id=uuid4(),
        tenant_id=tenant.id,
        revision_number=4,
        system_prompt_revision_id=uuid4(),
        profile_prompt_revision_id=uuid4(),
        tenant_prompt_revision_id=uuid4(),
        knowledge_base_revision_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_system_rollout_replaces_only_system_component() -> None:
    tenant = Tenant(
        slug="targeted-hotel",
        display_name="Targeted Hotel",
        business_type="hotel",
        active_prompt_set_revision_id=uuid4(),
    )
    active = active_prompt_set(tenant)
    tenants = AsyncMock()
    tenants.list_prompt_rollout_targets_for_update.return_value = [tenant]
    revisions = AsyncMock()
    revisions.revision.return_value = active
    service = PromptCompositionUseCases(tenants, revisions, AsyncMock())
    activate = AsyncMock(return_value=(active, True))
    service._activate_composition = activate
    target = uuid4()

    assert await service._rollout_component("system_prompt_revision_id", target) == (
        1,
        0,
    )
    assert activate.await_args is not None
    composition = activate.await_args.args[2]
    assert composition == {
        "system_prompt_revision_id": target,
        "profile_prompt_revision_id": active.profile_prompt_revision_id,
        "tenant_prompt_revision_id": active.tenant_prompt_revision_id,
        "knowledge_base_revision_id": active.knowledge_base_revision_id,
    }


@pytest.mark.asyncio
async def test_profile_rollout_uses_active_config_not_prompt_set_profile() -> None:
    tenant = Tenant(
        slug="profile-hotel",
        display_name="Profile Hotel",
        business_type="hotel",
        active_config_revision_id=uuid4(),
        active_prompt_set_revision_id=uuid4(),
    )
    active = active_prompt_set(tenant)
    tenants = AsyncMock()
    tenants.list_prompt_rollout_targets_for_update.return_value = [tenant]
    revisions = AsyncMock()
    revisions.revision.return_value = active
    configs = AsyncMock()
    configs.get.return_value = AsyncMock(
        schema_version=3,
        config={
            "schema_version": 3,
            "business": {"name": "Profile Hotel", "type": "hotel"},
            "localization": {
                "default_locale": "sk-SK",
                "timezone": "Europe/Bratislava",
            },
            "agent": {
                "display_name": "Amelia",
                "greeting": "Hello",
                "profile": "hotel_assistant",
            },
            "conversation": {"scope": "property_only"},
        },
    )
    service = PromptCompositionUseCases(tenants, revisions, configs)
    activate = AsyncMock(return_value=(active, True))
    service._activate_composition = activate
    target = uuid4()

    assert await service._rollout_component(
        "profile_prompt_revision_id", target, profile_key="hotel_assistant"
    ) == (1, 0)
    assert activate.await_args is not None
    composition = activate.await_args.args[2]
    assert composition["profile_prompt_revision_id"] == target
    assert composition["system_prompt_revision_id"] == (
        active.system_prompt_revision_id
    )
    assert composition["tenant_prompt_revision_id"] == (
        active.tenant_prompt_revision_id
    )
    assert composition["knowledge_base_revision_id"] == (
        active.knowledge_base_revision_id
    )


@pytest.mark.asyncio
async def test_plan_reports_missing_active_config_without_mutation() -> None:
    tenant = Tenant(
        slug="missing-config-hotel",
        display_name="Missing Config Hotel",
        business_type="hotel",
    )
    tenants = AsyncMock()
    tenants.get.return_value = tenant
    revisions = AsyncMock()
    service = PromptCompositionUseCases(tenants, revisions, AsyncMock())

    with pytest.raises(PromptSetResolutionError) as raised:
        await service.plan_prompt_set(tenant.id)

    assert raised.value.path == "tenant.active_config_revision_id"
    assert raised.value.code == "active_config_not_found"
    revisions.add.assert_not_awaited()
