from typing import Annotated
from uuid import UUID

from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.errors import (
    ConfigRevisionError,
    PromptRevisionError,
    TenantNotFoundError,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    PromptRevisionStatus,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    PromptCompositionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.service import (
    ConfigUseCases,
    PromptCompositionUseCases,
)
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession
from backend_core.runtime.voice.errors import VoiceRuntimeError
from backend_core.runtime.voice.repository import VoiceRuntimeRepository
from backend_core.runtime.voice.service import VoiceRuntimeUseCases
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/v1",
    tags=["admin:releases"],
    dependencies=[Depends(require_admin)],
)


class PublishAllResponse(BaseModel):
    published_sections: list[str]


class ReleaseUseCases:
    def __init__(self, session: DatabaseSession) -> None:
        self.session = session
        tenants = TenantRepository(session)
        configs = ConfigRevisionRepository(session)
        prompts = PromptCompositionRepository(session)
        self.configs = ConfigUseCases(
            tenants,
            configs,
            IntegrationConnectionRepository(session),
            prompts,
        )
        self.prompts = PromptCompositionUseCases(tenants, prompts, configs)
        self.runtimes = VoiceRuntimeUseCases(
            tenants,
            configs,
            VoiceRuntimeRepository(session),
        )

    async def rollback(self) -> None:
        await self.session.rollback()

    async def publish_platform(self) -> PublishAllResponse:
        published: list[str] = []
        runtime = await self.runtimes.platform_state()
        if runtime.draft_revision:
            await self.runtimes.publish_platform(runtime.draft_revision.id)
            published.append("runtime")
        system = next(
            (
                revision
                for revision in await self.prompts.list_system("default")
                if revision.status is PromptRevisionStatus.DRAFT
            ),
            None,
        )
        if system:
            await self.prompts.publish_system(system.id)
            published.append("system_prompt")
        for profile in await self.prompts.list_profiles():
            draft = next(
                (
                    revision
                    for revision in await self.prompts.list_profile(profile.key)
                    if revision.status is PromptRevisionStatus.DRAFT
                ),
                None,
            )
            if draft:
                await self.prompts.publish_profile(draft.id)
                published.append(f"profile_prompt:{profile.key}")
        return PublishAllResponse(published_sections=published)

    async def publish_tenant(self, tenant_id: UUID) -> PublishAllResponse:
        published: list[str] = []
        runtime = await self.runtimes.tenant_state(tenant_id)
        runtime_changed = runtime.draft_revision is not None
        if runtime.draft_revision:
            await self.runtimes.publish_tenant(tenant_id, runtime.draft_revision.id)
            published.append("runtime")
        config = next(
            (
                revision
                for revision in await self.configs.list_config_revisions(tenant_id)
                if revision.status is ConfigRevisionStatus.DRAFT
            ),
            None,
        )
        if config:
            await self.configs.publish_config_draft(tenant_id, config.id)
            published.append("agent")
        prompt = next(
            (
                revision
                for revision in await self.prompts.list_tenant_prompts(tenant_id)
                if revision.status is PromptRevisionStatus.DRAFT
            ),
            None,
        )
        if prompt:
            await self.prompts.publish_tenant_prompt(tenant_id, prompt.id)
            published.append("prompt")
        knowledge = next(
            (
                revision
                for revision in await self.prompts.list_knowledge_bases(tenant_id)
                if revision.status is PromptRevisionStatus.DRAFT
            ),
            None,
        )
        if knowledge:
            await self.prompts.publish_knowledge_base(tenant_id)
            published.append("knowledge_base")
        if config or prompt or knowledge:
            await self.prompts.apply_prompt_set(tenant_id)
        if runtime_changed or config:
            await self.runtimes.apply_voice_runtime(tenant_id)
        return PublishAllResponse(published_sections=published)


def get_release_use_cases(session: DatabaseSession) -> ReleaseUseCases:
    return ReleaseUseCases(session)


ReleaseDependency = Annotated[ReleaseUseCases, Depends(get_release_use_cases)]


@router.post("/platform/publish-all", response_model=PublishAllResponse)
async def publish_platform_all(use_cases: ReleaseDependency) -> PublishAllResponse:
    try:
        return await use_cases.publish_platform()
    except (ConfigRevisionError, PromptRevisionError, VoiceRuntimeError) as error:
        await use_cases.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "platform release conflict"
        ) from error


@router.post("/tenants/{tenant_id}/publish-all", response_model=PublishAllResponse)
async def publish_tenant_all(
    tenant_id: UUID, use_cases: ReleaseDependency
) -> PublishAllResponse:
    try:
        return await use_cases.publish_tenant(tenant_id)
    except TenantNotFoundError as error:
        await use_cases.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found") from error
    except (ConfigRevisionError, PromptRevisionError, VoiceRuntimeError) as error:
        await use_cases.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "tenant release conflict"
        ) from error
