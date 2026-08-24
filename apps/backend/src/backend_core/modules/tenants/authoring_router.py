from typing import Annotated
from uuid import UUID

from contracts.authoring import (
    AuthoringPlan,
    AuthoringState,
    TenantCapabilitiesAuthoring,
    TenantConfigAuthoring,
    TenantKnowledgeAuthoring,
    TenantPostCallAuthoring,
    TenantPromptAuthoring,
    TenantRuntimeAuthoring,
)
from contracts.tenant_components import TenantTelephonyConfig
from fastapi import APIRouter, Depends, Header, HTTPException, Response

from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.authoring import (
    AuthoringTranslationError,
    authoring_value,
    integration_readiness_warnings,
    semantic_plan,
    translate_capabilities,
    translate_post_call,
)
from backend_core.modules.tenants.component_router import _release
from backend_core.modules.tenants.component_schemas import (
    ComponentPublishRequest,
    TenantReleaseResponse,
)
from backend_core.modules.tenants.release_repository import (
    DraftConflictError,
    DraftExpectation,
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/authoring",
    tags=["admin:authoring"],
    dependencies=[Depends(require_admin)],
)


def _etag(version: int) -> str:
    return f'"{version}"'


def _version(value: str | None) -> int | None:
    return None if value is None else int(value.strip('"'))


async def _translated(
    component: TenantComponent,
    value: TenantCapabilitiesAuthoring | TenantPostCallAuthoring,
    tenant_id: UUID,
    session: DatabaseSession,
):
    try:
        if component is TenantComponent.CAPABILITIES:
            return await translate_capabilities(
                value, tenant_id=tenant_id, connections=IntegrationConnectionRepository(session)
            )
        return await translate_post_call(
            value, tenant_id=tenant_id, connections=IntegrationConnectionRepository(session)
        )
    except AuthoringTranslationError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "path": error.path, "message": error.message},
        ) from error


def _direct_payload(value):
    if isinstance(value, (TenantConfigAuthoring, TenantKnowledgeAuthoring)):
        return value.to_component().model_dump(mode="json")
    return value.model_dump(mode="json")


async def _plan(component, value, tenant_id, session) -> AuthoringPlan:
    translated = await _translated(component, value, tenant_id, session)
    draft = await TenantReleaseRepository(session).draft(component, tenant_id)
    result = semantic_plan(None if draft is None else draft.payload, translated.model_dump(mode="json"))
    operations = (
        [profile.execution for profile in value.capabilities.values() if not isinstance(profile, bool)]
        if component is TenantComponent.CAPABILITIES
        else [action.execution for action in value.actions]
    )
    warnings = await integration_readiness_warnings(
        operations, tenant_id, IntegrationConnectionRepository(session)
    )
    return AuthoringPlan.model_validate(
        {
            **result,
            "warnings": warnings,
            "impact": {
                "affected_components": [component.value],
                "new_release_required": bool(result["changes"]),
                "runtime_bundle_changes": bool(result["changes"]),
            },
        }
    )


async def _direct_value(component, value, tenant_id, session, response, if_match):
    translated = value.to_component() if isinstance(value, (TenantConfigAuthoring, TenantKnowledgeAuthoring)) else value
    try:
        draft = await TenantReleaseRepository(session).save_draft(
            component=component,
            tenant_id=tenant_id,
            payload=translated.model_dump(mode="json"),
            expected_version=if_match,
        )
    except DraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = _etag(draft.version)
    return AuthoringState(value=value, source="draft", etag=_etag(draft.version))


async def _direct_plan(component, value, tenant_id, session):
    translated = value.to_component() if isinstance(value, (TenantConfigAuthoring, TenantKnowledgeAuthoring)) else value
    draft = await TenantReleaseRepository(session).draft(component, tenant_id)
    result = semantic_plan(None if draft is None else draft.payload, translated.model_dump(mode="json"))
    return AuthoringPlan.model_validate({**result, "impact": {"affected_components": [component.value], "new_release_required": bool(result["changes"]), "runtime_bundle_changes": bool(result["changes"])}})


async def _read_state(component: TenantComponent, tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    repository = TenantReleaseRepository(session)
    draft = await repository.draft(component, tenant_id)
    active = await repository.active_release(tenant_id)
    revision = (
        None
        if active is None
        else await repository.revision(
            component, tenant_id, getattr(active, f"{component.value}_revision_id")
        )
    )
    connections = IntegrationConnectionRepository(session)
    draft_value = (
        None
        if draft is None
        else await authoring_value(
            component.value, draft.payload, tenant_id=tenant_id, connections=connections
        )
    )
    published_value = (
        None
        if revision is None
        else await authoring_value(
            component.value, revision.payload, tenant_id=tenant_id, connections=connections
        )
    )
    selected = draft_value if draft_value is not None else published_value
    return AuthoringState(
        value=None if selected is None else selected.model_dump(mode="json"),
        published_value=(
            None if published_value is None else published_value.model_dump(mode="json")
        ),
        source="draft" if draft_value is not None else "published" if published_value is not None else "empty",
        etag=None if draft is None else _etag(draft.version),
    )


@router.get("/config", response_model=AuthoringState)
async def read_config(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.AGENT, tenant_id, session)


@router.get("/runtime", response_model=AuthoringState)
async def read_runtime(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.RUNTIME, tenant_id, session)


@router.get("/prompt", response_model=AuthoringState)
async def read_prompt(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.PROMPT, tenant_id, session)


@router.get("/knowledge", response_model=AuthoringState)
async def read_knowledge(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.KNOWLEDGE, tenant_id, session)


@router.get("/capabilities", response_model=AuthoringState)
async def read_capabilities(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.CAPABILITIES, tenant_id, session)


@router.get("/post-call", response_model=AuthoringState)
async def read_post_call(tenant_id: UUID, session: DatabaseSession) -> AuthoringState:
    return await _read_state(TenantComponent.POST_CALL, tenant_id, session)


@router.post("/capabilities/plan", response_model=AuthoringPlan)
async def plan_capabilities(tenant_id: UUID, value: TenantCapabilitiesAuthoring, session: DatabaseSession):
    return await _plan(TenantComponent.CAPABILITIES, value, tenant_id, session)


@router.post("/post-call/plan", response_model=AuthoringPlan)
async def plan_post_call(tenant_id: UUID, value: TenantPostCallAuthoring, session: DatabaseSession):
    return await _plan(TenantComponent.POST_CALL, value, tenant_id, session)


@router.put("/capabilities", response_model=AuthoringState)
async def save_capabilities(
    tenant_id: UUID,
    value: TenantCapabilitiesAuthoring,
    session: DatabaseSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    translated = await _translated(TenantComponent.CAPABILITIES, value, tenant_id, session)
    try:
        draft = await TenantReleaseRepository(session).save_draft(
            component=TenantComponent.CAPABILITIES,
            tenant_id=tenant_id,
            payload=translated.model_dump(mode="json"),
            expected_version=_version(if_match),
        )
    except DraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = _etag(draft.version)
    return AuthoringState(value=value, source="draft", etag=_etag(draft.version))


@router.put("/post-call", response_model=AuthoringState)
async def save_post_call(
    tenant_id: UUID,
    value: TenantPostCallAuthoring,
    session: DatabaseSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    translated = await _translated(TenantComponent.POST_CALL, value, tenant_id, session)
    try:
        draft = await TenantReleaseRepository(session).save_draft(
            component=TenantComponent.POST_CALL,
            tenant_id=tenant_id,
            payload=translated.model_dump(mode="json"),
            expected_version=_version(if_match),
        )
    except DraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = _etag(draft.version)
    return AuthoringState(value=value, source="draft", etag=_etag(draft.version))


@router.post("/capabilities/publish", response_model=TenantReleaseResponse)
async def publish_capabilities(tenant_id: UUID, data: ComponentPublishRequest, session: DatabaseSession):
    release = await _release(
        session, tenant_id,
        [DraftExpectation(TenantComponent.CAPABILITIES, data.draft_id, data.version)],
        publish_all=False, comment=data.comment,
    )
    return TenantReleaseResponse.model_validate(release)


@router.post("/post-call/publish", response_model=TenantReleaseResponse)
async def publish_post_call(tenant_id: UUID, data: ComponentPublishRequest, session: DatabaseSession):
    release = await _release(
        session, tenant_id,
        [DraftExpectation(TenantComponent.POST_CALL, data.draft_id, data.version)],
        publish_all=False, comment=data.comment,
    )
    return TenantReleaseResponse.model_validate(release)


@router.post("/config/plan", response_model=AuthoringPlan)
async def plan_config(tenant_id: UUID, value: TenantConfigAuthoring, session: DatabaseSession):
    return await _direct_plan(TenantComponent.AGENT, value, tenant_id, session)


@router.post("/runtime/plan", response_model=AuthoringPlan)
async def plan_runtime(tenant_id: UUID, value: TenantRuntimeAuthoring, session: DatabaseSession):
    return await _direct_plan(TenantComponent.RUNTIME, value, tenant_id, session)


@router.post("/prompt/plan", response_model=AuthoringPlan)
async def plan_prompt(tenant_id: UUID, value: TenantPromptAuthoring, session: DatabaseSession):
    return await _direct_plan(TenantComponent.PROMPT, value, tenant_id, session)


@router.post("/knowledge/plan", response_model=AuthoringPlan)
async def plan_knowledge(tenant_id: UUID, value: TenantKnowledgeAuthoring, session: DatabaseSession):
    return await _direct_plan(TenantComponent.KNOWLEDGE, value, tenant_id, session)


@router.post("/telephony/plan", response_model=AuthoringPlan)
async def plan_telephony(tenant_id: UUID, value: TenantTelephonyConfig, session: DatabaseSession):
    return await _direct_plan(TenantComponent.TELEPHONY, value, tenant_id, session)


@router.put("/config", response_model=AuthoringState)
async def save_config(tenant_id: UUID, value: TenantConfigAuthoring, session: DatabaseSession, response: Response, if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    return await _direct_value(TenantComponent.AGENT, value, tenant_id, session, response, _version(if_match))


@router.put("/runtime", response_model=AuthoringState)
async def save_runtime(tenant_id: UUID, value: TenantRuntimeAuthoring, session: DatabaseSession, response: Response, if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    return await _direct_value(TenantComponent.RUNTIME, value, tenant_id, session, response, _version(if_match))


@router.put("/prompt", response_model=AuthoringState)
async def save_prompt(tenant_id: UUID, value: TenantPromptAuthoring, session: DatabaseSession, response: Response, if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    return await _direct_value(TenantComponent.PROMPT, value, tenant_id, session, response, _version(if_match))


@router.put("/knowledge", response_model=AuthoringState)
async def save_knowledge(tenant_id: UUID, value: TenantKnowledgeAuthoring, session: DatabaseSession, response: Response, if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    return await _direct_value(TenantComponent.KNOWLEDGE, value, tenant_id, session, response, _version(if_match))
