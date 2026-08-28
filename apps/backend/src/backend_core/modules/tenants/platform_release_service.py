from dataclasses import dataclass

from contracts.voice_runtime import PlatformRuntimePolicy
from pydantic import ValidationError

from backend_core.modules.tenants.platform_release_models import (
    PlatformProfilePromptComponentRevision,
    PlatformProfilePromptDraft,
    PlatformRelease,
    PlatformReleaseProfilePrompt,
    PlatformRuntimeComponentRevision,
    PlatformRuntimeDraft,
    PlatformSystemPromptComponentRevision,
    PlatformSystemPromptDraft,
)
from backend_core.modules.tenants.platform_release_repository import (
    PlatformReleaseRepository,
)
from backend_core.modules.tenants.release_compiler import PlatformBundleInput


class PlatformReleaseError(Exception):
    pass


class PlatformDraftConflictError(PlatformReleaseError):
    pass


class PlatformNotReadyError(PlatformReleaseError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformPublishSnapshot:
    runtime_version: int | None
    system_prompt_version: int | None
    profile_prompt_versions: dict[str, int]


class PlatformReleaseUseCases:
    """Typed platform drafts sealed into a release; no latest lookup reaches runtime."""

    def __init__(self, repository: PlatformReleaseRepository) -> None:
        self._repository = repository

    async def ensure_initial_drafts(self) -> None:
        if await self._repository.active_release() is not None:
            return
        if await self._repository.runtime_draft() is None:
            await self.save_runtime(
                PlatformRuntimePolicy.model_validate(
                    {
                        "llm": {
                            "provider": "azure_openai",
                            "model": "gpt-4.1",
                            "temperature": 0.2,
                        },
                        "stt": {
                            "provider": "elevenlabs",
                            "model": "scribe",
                            "interim_preflight": {
                                "enabled": False,
                                "min_transcript_chars": 20,
                                "min_growth_chars": 12,
                                "max_generations_per_turn": 2,
                            },
                            "server_vad": {
                                "silence_threshold_seconds": 1,
                                "activity_threshold": 0.5,
                                "min_speech_ms": 100,
                                "min_silence_ms": 200,
                            },
                        },
                        "tts": {
                            "provider": "elevenlabs",
                            "model": "turbo",
                            "voice_id": "voice",
                            "min_sentence_chars": 20,
                        },
                        "local_vad": {
                            "min_speech_seconds": 0.2,
                            "min_silence_seconds": 0.4,
                            "activation_threshold": 0.5,
                        },
                        "turn": {
                            "detection": "stt",
                            "min_endpointing_delay_seconds": 0.2,
                            "max_endpointing_delay_seconds": 1,
                        },
                    }
                ),
                None,
            )
        if await self._repository.system_prompt_draft() is None:
            await self.save_system_prompt(
                "You are a customer-facing business voice assistant.", None
            )

    async def save_runtime(
        self, policy: PlatformRuntimePolicy, expected_version: int | None
    ) -> PlatformRuntimeDraft:
        await self._repository.control_for_update()
        draft = await self._repository.runtime_draft_for_update()
        payload = policy.model_dump(mode="json")
        if draft is None:
            if expected_version is not None:
                raise PlatformDraftConflictError
            draft = PlatformRuntimeDraft(payload=payload)
            await self._repository.add(draft)
        elif draft.version != expected_version:
            raise PlatformDraftConflictError
        elif draft.payload != payload:
            draft.payload = payload
            draft.version += 1
            await self._repository.add(draft)
        return draft

    async def save_system_prompt(
        self, text: str, expected_version: int | None
    ) -> PlatformSystemPromptDraft:
        await self._repository.control_for_update()
        draft = await self._repository.system_prompt_draft_for_update()
        if draft is None:
            if expected_version is not None:
                raise PlatformDraftConflictError
            draft = PlatformSystemPromptDraft(text=text)
            await self._repository.add(draft)
        elif draft.version != expected_version:
            raise PlatformDraftConflictError
        elif draft.text != text:
            draft.text = text
            draft.version += 1
            await self._repository.add(draft)
        return draft

    async def save_profile_prompt(
        self, profile: str, text: str, expected_version: int | None
    ) -> PlatformProfilePromptDraft:
        await self._repository.control_for_update()
        drafts = await self._repository.profile_drafts_for_update()
        draft = next((item for item in drafts if item.profile == profile), None)
        if draft is None:
            if expected_version is not None:
                raise PlatformDraftConflictError
            draft = PlatformProfilePromptDraft(profile=profile, text=text)
            await self._repository.add(draft)
        elif draft.version != expected_version:
            raise PlatformDraftConflictError
        elif draft.text != text:
            draft.text = text
            draft.version += 1
            await self._repository.add(draft)
        return draft

    async def publish(self, snapshot: PlatformPublishSnapshot) -> PlatformRelease:
        control = await self._repository.control_for_update()
        runtime_draft = await self._repository.runtime_draft_for_update()
        system_draft = await self._repository.system_prompt_draft_for_update()
        profile_drafts = await self._repository.profile_drafts_for_update()
        self._validate_snapshot(runtime_draft, system_draft, profile_drafts, snapshot)
        active = await self._repository.active_release()
        if active is None and (runtime_draft is None or system_draft is None):
            raise PlatformNotReadyError

        runtime = await self._seal_runtime(runtime_draft, active)
        system_prompt = await self._seal_system_prompt(system_draft, active)
        profiles = await self._profiles(active, profile_drafts)
        release = PlatformRelease(
            release_number=await self._repository.next_release_number(),
            runtime_revision_id=runtime.id,
            system_prompt_revision_id=system_prompt.id,
        )
        await self._repository.add(release)
        for profile, revision in profiles.items():
            await self._repository.add(
                PlatformReleaseProfilePrompt(
                    release_id=release.id,
                    profile=profile,
                    profile_prompt_revision_id=revision.id,
                )
            )
        for draft in (runtime_draft, system_draft, *profile_drafts):
            if draft is not None:
                await self._repository.delete(draft)
        control.active_release_id = release.id
        await self._repository.add(control)
        return release

    async def input_for_profile(self, profile: str) -> PlatformBundleInput:
        active = await self._repository.active_release()
        if active is None:
            raise PlatformNotReadyError
        runtime = await self._repository.runtime_revision(active.runtime_revision_id)
        system = await self._repository.system_prompt_revision(
            active.system_prompt_revision_id
        )
        prompt = await self._repository.profile_revision_for_release(active.id, profile)
        if runtime is None or system is None or prompt is None:
            raise PlatformNotReadyError
        try:
            policy = PlatformRuntimePolicy.model_validate(runtime.payload)
        except ValidationError as error:
            raise PlatformNotReadyError from error
        return PlatformBundleInput(
            runtime_revision_id=runtime.id,
            system_prompt_revision_id=system.id,
            profile_prompt_revision_id=prompt.id,
            runtime_policy=policy,
            system_prompt=system.text,
            profile_prompt=prompt.text,
        )

    @staticmethod
    def _validate_snapshot(
        runtime: PlatformRuntimeDraft | None,
        system: PlatformSystemPromptDraft | None,
        profiles: list[PlatformProfilePromptDraft],
        snapshot: PlatformPublishSnapshot,
    ) -> None:
        if (runtime is None) != (snapshot.runtime_version is None) or (
            runtime is not None and runtime.version != snapshot.runtime_version
        ):
            raise PlatformDraftConflictError
        if (system is None) != (snapshot.system_prompt_version is None) or (
            system is not None and system.version != snapshot.system_prompt_version
        ):
            raise PlatformDraftConflictError
        versions = {item.profile: item.version for item in profiles}
        if versions != snapshot.profile_prompt_versions:
            raise PlatformDraftConflictError

    async def _seal_runtime(
        self, draft: PlatformRuntimeDraft | None, active: PlatformRelease | None
    ) -> PlatformRuntimeComponentRevision:
        if draft is None:
            assert active is not None
            revision = await self._repository.runtime_revision(
                active.runtime_revision_id
            )
            assert revision is not None
            return revision
        revision = PlatformRuntimeComponentRevision(
            revision_number=await self._repository.next_number(
                PlatformRuntimeComponentRevision
            ),
            payload=draft.payload,
        )
        await self._repository.add(revision)
        return revision

    async def _seal_system_prompt(
        self,
        draft: PlatformSystemPromptDraft | None,
        active: PlatformRelease | None,
    ) -> PlatformSystemPromptComponentRevision:
        if draft is None:
            assert active is not None
            revision = await self._repository.system_prompt_revision(
                active.system_prompt_revision_id
            )
            assert revision is not None
            return revision
        revision = PlatformSystemPromptComponentRevision(
            revision_number=await self._repository.next_number(
                PlatformSystemPromptComponentRevision
            ),
            text=draft.text,
        )
        await self._repository.add(revision)
        return revision

    async def _profiles(
        self,
        active: PlatformRelease | None,
        drafts: list[PlatformProfilePromptDraft],
    ) -> dict[str, PlatformProfilePromptComponentRevision]:
        profiles: dict[str, PlatformProfilePromptComponentRevision] = {}
        if active is not None:
            for profile in await self._repository.release_profiles(active.id):
                revision = await self._repository.profile_revision(
                    profile.profile_prompt_revision_id
                )
                assert revision is not None
                profiles[profile.profile] = revision
        for draft in drafts:
            revision = PlatformProfilePromptComponentRevision(
                profile=draft.profile,
                revision_number=await self._repository.next_number(
                    PlatformProfilePromptComponentRevision, profile=draft.profile
                ),
                text=draft.text,
            )
            await self._repository.add(revision)
            profiles[draft.profile] = revision
        return profiles
