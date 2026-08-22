from typing import Annotated, Any

from contracts.voice_runtime import PlatformRuntimePolicy
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from backend_core.modules.tenants.platform_release_repository import (
    PlatformReleaseRepository,
)
from backend_core.modules.tenants.platform_release_service import (
    PlatformDraftConflictError,
    PlatformNotReadyError,
    PlatformPublishSnapshot,
    PlatformReleaseUseCases,
)
from backend_core.platform.auth import require_admin
from backend_core.platform.database import DatabaseSession

router = APIRouter(
    prefix="/admin/v1/platform/components",
    tags=["admin:platform-components"],
    dependencies=[Depends(require_admin)],
)


class RuntimeDraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: PlatformRuntimePolicy


class PromptDraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1_000_000)


class DraftResponse(BaseModel):
    id: str
    version: int


class PlatformPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_version: int | None = Field(default=None, ge=1)
    system_prompt_version: int | None = Field(default=None, ge=1)
    profile_prompt_versions: dict[str, int] = Field(default_factory=dict)


class PlatformReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    release_number: int
    runtime_revision_id: str
    system_prompt_revision_id: str


class PlatformDraftState(BaseModel):
    id: str
    version: int
    value: dict[str, Any] | str


class PlatformStateResponse(BaseModel):
    runtime_draft: PlatformDraftState | None
    system_prompt_draft: PlatformDraftState | None
    profile_prompt_drafts: dict[str, PlatformDraftState]
    active_release: PlatformReleaseResponse | None
    active_runtime: dict[str, Any] | None
    active_system_prompt: str | None
    active_profile_prompts: dict[str, str]


def _if_match(value: str | None) -> int | None:
    if value is None:
        return None
    if len(value) < 3 or value[0] != '"' or value[-1] != '"' or not value[1:-1].isdigit():
        raise HTTPException(status_code=400, detail="If-Match must be a quoted version")
    return int(value[1:-1])


def _use_cases(session: DatabaseSession) -> PlatformReleaseUseCases:
    return PlatformReleaseUseCases(PlatformReleaseRepository(session))


@router.get("/state", response_model=PlatformStateResponse)
async def state(session: DatabaseSession) -> PlatformStateResponse:
    repository = PlatformReleaseRepository(session)
    runtime = await repository.runtime_draft()
    system = await repository.system_prompt_draft()
    profiles = await repository.profile_drafts()
    active = await repository.active_release()
    active_runtime = (
        None
        if active is None
        else await repository.runtime_revision(active.runtime_revision_id)
    )
    active_system = (
        None
        if active is None
        else await repository.system_prompt_revision(active.system_prompt_revision_id)
    )
    active_profiles = (
        [] if active is None else await repository.release_profiles(active.id)
    )
    active_profile_prompts: dict[str, str] = {}
    for item in active_profiles:
        revision = await repository.profile_revision(item.profile_prompt_revision_id)
        if revision is not None:
            active_profile_prompts[item.profile] = revision.text
    return PlatformStateResponse(
        runtime_draft=(
            None
            if runtime is None
            else PlatformDraftState(
                id=str(runtime.id), version=runtime.version, value=runtime.payload
            )
        ),
        system_prompt_draft=(
            None
            if system is None
            else PlatformDraftState(
                id=str(system.id), version=system.version, value=system.text
            )
        ),
        profile_prompt_drafts={
            draft.profile: PlatformDraftState(
                id=str(draft.id), version=draft.version, value=draft.text
            )
            for draft in profiles
        },
        active_release=(
            None
            if active is None
            else PlatformReleaseResponse.model_validate(active)
        ),
        active_runtime=(None if active_runtime is None else active_runtime.payload),
        active_system_prompt=(None if active_system is None else active_system.text),
        active_profile_prompts=active_profile_prompts,
    )


@router.put("/runtime/draft", response_model=DraftResponse)
async def save_runtime(
    data: RuntimeDraftWrite,
    response: Response,
    session: DatabaseSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DraftResponse:
    try:
        draft = await _use_cases(session).save_runtime(data.policy, _if_match(if_match))
    except PlatformDraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = f'"{draft.version}"'
    return DraftResponse(id=str(draft.id), version=draft.version)


@router.put("/system-prompt/draft", response_model=DraftResponse)
async def save_system_prompt(
    data: PromptDraftWrite,
    response: Response,
    session: DatabaseSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DraftResponse:
    try:
        draft = await _use_cases(session).save_system_prompt(data.text, _if_match(if_match))
    except PlatformDraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = f'"{draft.version}"'
    return DraftResponse(id=str(draft.id), version=draft.version)


@router.put("/profiles/{profile}/draft", response_model=DraftResponse)
async def save_profile_prompt(
    profile: str,
    data: PromptDraftWrite,
    response: Response,
    session: DatabaseSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DraftResponse:
    try:
        draft = await _use_cases(session).save_profile_prompt(
            profile, data.text, _if_match(if_match)
        )
    except PlatformDraftConflictError as error:
        raise HTTPException(status_code=412, detail="draft version does not match If-Match") from error
    response.headers["ETag"] = f'"{draft.version}"'
    return DraftResponse(id=str(draft.id), version=draft.version)


@router.post("/publish", response_model=PlatformReleaseResponse)
async def publish(
    data: PlatformPublishRequest, session: DatabaseSession
) -> PlatformReleaseResponse:
    try:
        release = await _use_cases(session).publish(
            PlatformPublishSnapshot(
                runtime_version=data.runtime_version,
                system_prompt_version=data.system_prompt_version,
                profile_prompt_versions=data.profile_prompt_versions,
            )
        )
    except PlatformDraftConflictError as error:
        raise HTTPException(status_code=412, detail="platform draft snapshot is stale") from error
    except PlatformNotReadyError as error:
        raise HTTPException(status_code=409, detail="platform initial release is incomplete") from error
    return PlatformReleaseResponse.model_validate(release)
