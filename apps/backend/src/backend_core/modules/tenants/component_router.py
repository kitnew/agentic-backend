from typing import Annotated, Any
from uuid import UUID

from contracts.tenant_components import (
    TenantAgentConfig,
    TenantCapabilitiesConfig,
    TenantKnowledgeConfig,
    TenantPromptConfig,
    TenantTelephonyConfig,
)
from contracts.voice_runtime import TenantRuntimeOverride
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ValidationError

from backend_core.modules.tenants.component_schemas import (
    ComponentDraftResponse,
    ComponentDraftWrite,
    ComponentPublishRequest,
    ComponentRevisionResponse,
    ComponentStateResponse,
    PublishAllRequest,
    RollbackRequest,
    TenantReleaseResponse,
)
from backend_core.modules.tenants.platform_release_repository import (
    PlatformReleaseRepository,
)
from backend_core.modules.tenants.platform_release_service import (
    PlatformNotReadyError,
    PlatformReleaseUseCases,
)
from backend_core.modules.tenants.release_compiler import compile_tenant_runtime_bundle
from backend_core.modules.tenants.release_repository import (
    DraftConflictError,
    DraftExpectation,
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.release_service import (
    ComponentDraftValidationError,
    InitialConfigurationIncompleteError,
    TenantNotInitializedError,
    TenantReleaseError,
    TenantReleaseUseCases,
)
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/components",
    tags=["admin:tenant-components"],
    dependencies=[Depends(require_admin)],
)

_MODELS: dict[TenantComponent, type[BaseModel]] = {
    TenantComponent.RUNTIME: TenantRuntimeOverride,
    TenantComponent.AGENT: TenantAgentConfig,
    TenantComponent.PROMPT: TenantPromptConfig,
    TenantComponent.KNOWLEDGE: TenantKnowledgeConfig,
    TenantComponent.CAPABILITIES: TenantCapabilitiesConfig,
    TenantComponent.TELEPHONY: TenantTelephonyConfig,
}


def _component(value: str) -> TenantComponent:
    try:
        return TenantComponent(value)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="unknown tenant component") from error


def _etag(version: int) -> str:
    return f'"{version}"'


def _if_match(value: str | None) -> int | None:
    if value is None:
        return None
    if len(value) < 3 or value[0] != '"' or value[-1] != '"' or not value[1:-1].isdigit():
        raise HTTPException(status_code=400, detail="If-Match must be a quoted version")
    return int(value[1:-1])


def _payload(component: TenantComponent, value: dict[str, Any]) -> dict[str, Any]:
    try:
        return _MODELS[component].model_validate(value).model_dump(mode="json")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


async def _release(
    session: DatabaseSession,
    tenant_id: UUID,
    expectations: list[DraftExpectation],
    *,
    publish_all: bool,
    comment: str | None,
):
    releases = TenantReleaseRepository(session)
    selected_agent = next(
        (item for item in expectations if item.component is TenantComponent.AGENT), None
    )
    agent_draft = await releases.draft(TenantComponent.AGENT, tenant_id)
    active = await releases.active_release(tenant_id)
    agent_payload = (
        agent_draft.payload
        if selected_agent is not None and agent_draft is not None
        else None
    )
    if agent_payload is None and active is not None:
        active_agent = await releases.revision(
            TenantComponent.AGENT, tenant_id, active.agent_revision_id
        )
        agent_payload = None if active_agent is None else active_agent.payload
    if agent_payload is None:
        raise HTTPException(status_code=409, detail="agent component is required")
    try:
        profile = TenantAgentConfig.model_validate(agent_payload).agent.profile
        platform = await PlatformReleaseUseCases(
            PlatformReleaseRepository(session)
        ).input_for_profile(profile)
    except PlatformNotReadyError as error:
        raise HTTPException(status_code=409, detail="platform release is not ready") from error

    def compile(components):
        return compile_tenant_runtime_bundle(
            tenant_id=tenant_id,
            runtime_revision_id=components.runtime.id,
            runtime=TenantRuntimeOverride.model_validate(components.runtime.payload),
            agent_revision_id=components.agent.id,
            agent=TenantAgentConfig.model_validate(components.agent.payload),
            prompt_revision_id=components.prompt.id,
            prompt=TenantPromptConfig.model_validate(components.prompt.payload),
            knowledge_revision_id=components.knowledge.id,
            knowledge=TenantKnowledgeConfig.model_validate(components.knowledge.payload),
            capabilities_revision_id=components.capabilities.id,
            capabilities=TenantCapabilitiesConfig.model_validate(
                components.capabilities.payload
            ),
            telephony_revision_id=components.telephony.id,
            telephony=TenantTelephonyConfig.model_validate(components.telephony.payload),
            platform=platform,
            compiler_build_id="component-release-v1",
        )

    try:
        return await TenantReleaseUseCases(releases).publish(
            tenant_id,
            expectations,
            compile,
            comment=comment,
            publish_all=publish_all,
        )
    except DraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft no longer matches snapshot") from error
    except InitialConfigurationIncompleteError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": "initial configuration is incomplete", "missing": error.missing},
        ) from error
    except (TenantNotInitializedError, TenantReleaseError, ComponentDraftValidationError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{component}/draft", response_model=ComponentDraftResponse)
async def get_draft(component: str, tenant_id: UUID, session: DatabaseSession) -> ComponentDraftResponse:
    kind = _component(component)
    draft = await TenantReleaseRepository(session).draft(kind, tenant_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="component draft not found")
    return ComponentDraftResponse(
        id=draft.id, component=kind.value, payload=draft.payload, version=draft.version,
        comment=draft.comment, updated_at=draft.updated_at,
    )


@router.get("/{component}", response_model=ComponentStateResponse)
async def component_state(
    component: str, tenant_id: UUID, session: DatabaseSession
) -> ComponentStateResponse:
    kind = _component(component)
    releases = TenantReleaseRepository(session)
    draft = await releases.draft(kind, tenant_id)
    active = await releases.active_release(tenant_id)
    revision = (
        None
        if active is None
        else await releases.revision(kind, tenant_id, getattr(active, f"{kind}_revision_id"))
    )
    return ComponentStateResponse(
        component=kind.value,
        draft=(
            None
            if draft is None
            else ComponentDraftResponse(
                id=draft.id,
                component=kind.value,
                payload=draft.payload,
                version=draft.version,
                comment=draft.comment,
                updated_at=draft.updated_at,
            )
        ),
        active_revision=(
            None
            if revision is None
            else ComponentRevisionResponse(
                id=revision.id,
                revision_number=revision.revision_number,
                payload=revision.payload,
                comment=revision.comment,
                sealed_at=revision.sealed_at,
            )
        ),
    )


@router.put("/{component}/draft", response_model=ComponentDraftResponse)
async def save_draft(
    component: str,
    tenant_id: UUID,
    data: ComponentDraftWrite,
    session: DatabaseSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ComponentDraftResponse:
    kind = _component(component)
    try:
        draft = await TenantReleaseRepository(session).save_draft(
            component=kind, tenant_id=tenant_id, payload=_payload(kind, data.payload),
            expected_version=_if_match(if_match), comment=data.comment,
        )
    except DraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = _etag(draft.version)
    return ComponentDraftResponse(
        id=draft.id, component=kind.value, payload=draft.payload, version=draft.version,
        comment=draft.comment, updated_at=draft.updated_at,
    )


@router.post("/{component}/publish", response_model=TenantReleaseResponse)
async def publish_component(
    component: str, tenant_id: UUID, data: ComponentPublishRequest, session: DatabaseSession
) -> TenantReleaseResponse:
    release = await _release(
        session, tenant_id,
        [DraftExpectation(_component(component), data.draft_id, data.version)],
        publish_all=False, comment=data.comment,
    )
    return TenantReleaseResponse.model_validate(release)


@router.post("/publish-all", response_model=TenantReleaseResponse)
async def publish_all(
    tenant_id: UUID, data: PublishAllRequest, session: DatabaseSession
) -> TenantReleaseResponse:
    release = await _release(
        session, tenant_id,
        [
            DraftExpectation(_component(item.component), item.draft_id, item.version)
            for item in data.drafts
        ],
        publish_all=True, comment=data.comment,
    )
    return TenantReleaseResponse.model_validate(release)


@router.post("/rollback", response_model=TenantReleaseResponse)
async def rollback(
    tenant_id: UUID, data: RollbackRequest, session: DatabaseSession
) -> TenantReleaseResponse:
    try:
        release = await TenantReleaseUseCases(TenantReleaseRepository(session)).rollback(
            tenant_id, data.target_release_id
        )
    except TenantReleaseError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return TenantReleaseResponse.model_validate(release)
