from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from backend_core.interfaces.http.releases import ReleaseUseCases, publish_platform_all
from backend_core.modules.tenants.errors import ConfigRevisionError
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    PromptRevisionStatus,
)
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_platform_publish_all_publishes_each_saved_draft_once() -> None:
    release = ReleaseUseCases.__new__(ReleaseUseCases)
    runtime = SimpleNamespace(id=uuid4())
    system = SimpleNamespace(id=uuid4(), status=PromptRevisionStatus.DRAFT)
    profile = SimpleNamespace(id=uuid4(), status=PromptRevisionStatus.DRAFT)
    release.runtimes = SimpleNamespace(
        platform_state=AsyncMock(return_value=SimpleNamespace(draft_revision=runtime)),
        publish_platform=AsyncMock(),
    )
    release.prompts = SimpleNamespace(
        list_system=AsyncMock(return_value=[system]),
        publish_system=AsyncMock(),
        list_profiles=AsyncMock(return_value=[SimpleNamespace(key="hotel_assistant")]),
        list_profile=AsyncMock(return_value=[profile]),
        publish_profile=AsyncMock(),
    )

    result = await release.publish_platform()

    assert result.published_sections == [
        "runtime",
        "system_prompt",
        "profile_prompt:hotel_assistant",
    ]
    release.runtimes.publish_platform.assert_awaited_once_with(runtime.id)
    release.prompts.publish_system.assert_awaited_once_with(system.id)
    release.prompts.publish_profile.assert_awaited_once_with(profile.id)


@pytest.mark.asyncio
async def test_tenant_publish_all_publishes_then_applies_one_release() -> None:
    release = ReleaseUseCases.__new__(ReleaseUseCases)
    tenant_id = uuid4()
    runtime = SimpleNamespace(id=uuid4())
    config = SimpleNamespace(id=uuid4(), status=ConfigRevisionStatus.DRAFT)
    prompt = SimpleNamespace(id=uuid4(), status=PromptRevisionStatus.DRAFT)
    knowledge = SimpleNamespace(id=uuid4(), status=PromptRevisionStatus.DRAFT)
    release.runtimes = SimpleNamespace(
        tenant_state=AsyncMock(return_value=SimpleNamespace(draft_revision=runtime)),
        publish_tenant=AsyncMock(),
        apply_voice_runtime=AsyncMock(),
    )
    release.configs = SimpleNamespace(
        list_config_revisions=AsyncMock(return_value=[config]),
        publish_config_draft=AsyncMock(),
    )
    release.prompts = SimpleNamespace(
        list_tenant_prompts=AsyncMock(return_value=[prompt]),
        publish_tenant_prompt=AsyncMock(),
        list_knowledge_bases=AsyncMock(return_value=[knowledge]),
        publish_knowledge_base=AsyncMock(),
        apply_prompt_set=AsyncMock(),
    )

    result = await release.publish_tenant(tenant_id)

    assert result.published_sections == ["runtime", "agent", "prompt", "knowledge_base"]
    release.prompts.apply_prompt_set.assert_awaited_once_with(tenant_id)
    release.runtimes.apply_voice_runtime.assert_awaited_once_with(tenant_id)


@pytest.mark.asyncio
async def test_publish_all_rolls_back_before_returning_a_conflict() -> None:
    release = SimpleNamespace(
        publish_platform=AsyncMock(side_effect=ConfigRevisionError()),
        rollback=AsyncMock(),
    )

    with pytest.raises(HTTPException) as caught:
        await publish_platform_all(release)

    assert caught.value.status_code == 409
    release.rollback.assert_awaited_once()
