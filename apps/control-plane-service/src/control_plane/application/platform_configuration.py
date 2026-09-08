from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.transactions import PlatformCommandScope
from control_plane.application.system_configuration import (
    ConfigurationChange,
    ValidationIssue,
)
from control_plane.domain.catalogs import CatalogStatus
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    InteractionModeScope,
    PlatformScope,
    ProfileScope,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.frozen_components import (
    InteractionPrompt,
    ProfilePrompt,
    SystemPrompt,
)


class DesiredProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=2000)
    status: CatalogStatus
    prompt: ProfilePrompt


class DesiredInteractionMode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=2000)
    status: CatalogStatus
    prompt: InteractionPrompt


class PlatformConfigurationDesired(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    system_prompt: SystemPrompt
    profiles: tuple[DesiredProfile, ...]
    interaction_modes: tuple[DesiredInteractionMode, ...]

    @model_validator(mode="after")
    def keys_are_unique(self):
        for label, entries in (
            ("profile", self.profiles),
            ("interaction mode", self.interaction_modes),
        ):
            keys = [entry.key for entry in entries]
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} key")
        return self


T = TypeVar("T", bound=BaseModel)


class PromptState[T](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    active: T | None = None
    draft: T | None = None


class ProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    name: str
    description: str
    status: CatalogStatus
    prompt: PromptState[ProfilePrompt]


class InteractionModeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    name: str
    description: str
    status: CatalogStatus
    prompt: PromptState[InteractionPrompt]


class ConfigurationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    has_drafts: bool
    publishable: bool


class PlatformConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    system_prompt: PromptState[SystemPrompt]
    profiles: tuple[ProfileConfiguration, ...]
    interaction_modes: tuple[InteractionModeConfiguration, ...]
    status: ConfigurationStatus


@dataclass(frozen=True, slots=True)
class PlatformConfigurationPlan:
    valid: bool
    catalog_changes: tuple[ConfigurationChange, ...]
    draft_changes: tuple[ConfigurationChange, ...]
    warnings: tuple[str, ...]
    errors: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class PlatformConfigurationApplyResult:
    catalogs_updated: tuple[str, ...]
    drafts_saved: tuple[str, ...]
    unchanged: tuple[str, ...]
    configuration: PlatformConfiguration


@dataclass(frozen=True, slots=True)
class PlatformConfigurationPublishResult:
    published_components: tuple[str, ...]
    unchanged_components: tuple[str, ...]
    configuration: PlatformConfiguration


class PlatformConfigurationError(Exception):
    code = "configuration_invalid"


class PlatformConfigurationPreconditionFailed(PlatformConfigurationError):
    code = "precondition_failed"


class PlatformConfigurationService:
    def __init__(
        self,
        registry: ComponentDefinitionRegistry,
        command_scope: PlatformCommandScope,
    ) -> None:
        self._registry = registry
        self._command_scope = command_scope

    async def get(self) -> PlatformConfiguration:
        async with self._command_scope() as (repository, _):
            return await self._load(repository)

    async def plan(
        self, desired: PlatformConfigurationDesired
    ) -> PlatformConfigurationPlan:
        async with self._command_scope() as (repository, _):
            current = await self._load(repository)
        return self._plan(current, desired)

    async def apply(
        self,
        desired: PlatformConfigurationDesired,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> PlatformConfigurationApplyResult:
        fingerprint = request_fingerprint(
            {"desired": desired.model_dump(mode="json"), "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "platform_configuration.apply", idempotency_key
            )
            if replay is not None:
                return self._replay_apply(replay, fingerprint)
            current = await self._load(repository, lock=True)
            self._require_token(current, expected_token)
            plan = self._plan(current, desired)
            if plan.errors:
                raise PlatformConfigurationError(plan.errors[0].message)

            updated: list[str] = []
            for entry in desired.profiles:
                profile_before = next(
                    (item for item in current.profiles if item.key == entry.key), None
                )
                if profile_before is None or _catalog_value(
                    profile_before
                ) != _catalog_value(entry):
                    await repository.put_profile(
                        entry.key,
                        entry.name,
                        entry.description,
                        entry.status,
                        principal,
                    )
                    updated.append(f"profiles.{entry.key}")
            for mode_entry in desired.interaction_modes:
                mode_before = next(
                    (
                        item
                        for item in current.interaction_modes
                        if item.key == mode_entry.key
                    ),
                    None,
                )
                if mode_before is None or _catalog_value(mode_before) != _catalog_value(
                    mode_entry
                ):
                    await repository.put_interaction_mode(
                        mode_entry.key,
                        mode_entry.name,
                        mode_entry.description,
                        mode_entry.status,
                        principal,
                    )
                    updated.append(f"interaction_modes.{mode_entry.key}")

            saved: list[str] = []
            for path, address, value in self._desired_prompts(desired):
                _, draft, active = await repository.get_component(address, lock=True)
                payload = value.model_dump(mode="json")
                if draft is not None and draft.value == payload:
                    continue
                if draft is not None and active is not None and active.value == payload:
                    await repository.discard_draft(address, draft.version)
                    saved.append(path)
                    continue
                if draft is None and active is not None and active.value == payload:
                    continue
                definition = self._registry.resolve(address)
                await repository.save_draft(
                    address,
                    payload,
                    definition.schema_version,
                    draft.version if draft is not None else None,
                    active.id if active is not None else None,
                    principal,
                )
                saved.append(path)
            configuration = await self._load(repository)
            changed = set(updated) | set(saved)
            result = PlatformConfigurationApplyResult(
                tuple(updated),
                tuple(saved),
                tuple(path for path in self._all_paths(desired) if path not in changed),
                configuration,
            )
            await replays.add(
                principal,
                "platform_configuration.apply",
                idempotency_key,
                fingerprint,
                self._apply_result(result),
            )
            return result

    async def publish(
        self,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> PlatformConfigurationPublishResult:
        fingerprint = request_fingerprint({"if_match": expected_token})
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "platform_configuration.publish", idempotency_key
            )
            if replay is not None:
                return self._replay_publish(replay, fingerprint)
            current = await self._load(repository, lock=True)
            self._require_token(current, expected_token)
            published: list[str] = []
            unchanged: list[str] = []
            for path, address in self._current_prompt_addresses(current):
                exists, draft, _ = await repository.get_component(address, lock=True)
                if not exists or draft is None:
                    unchanged.append(path)
                    continue
                definition = self._registry.resolve(address)
                definition.deserialize(draft.value)
                await repository.publish_draft(
                    address, draft.version, principal, definition
                )
                published.append(path)
            configuration = await self._load(repository)
            result = PlatformConfigurationPublishResult(
                tuple(published), tuple(unchanged), configuration
            )
            await replays.add(
                principal,
                "platform_configuration.publish",
                idempotency_key,
                fingerprint,
                self._publish_result(result),
            )
            return result

    @staticmethod
    def concurrency_token(configuration: PlatformConfiguration) -> str:
        return opaque_concurrency_token(configuration.model_dump(mode="json"))

    def _require_token(
        self, configuration: PlatformConfiguration, expected_token: str
    ) -> None:
        initial = (
            not configuration.profiles
            and not configuration.interaction_modes
            and configuration.system_prompt.active is None
            and configuration.system_prompt.draft is None
        )
        expected = "*" if initial else self.concurrency_token(configuration)
        if expected_token != expected:
            raise PlatformConfigurationPreconditionFailed(
                "platform configuration precondition failed"
            )

    async def _load(self, repository, *, lock=False) -> PlatformConfiguration:
        profiles = tuple(
            sorted(await repository.list_profiles(lock=lock), key=lambda x: x.key)
        )
        modes = tuple(
            sorted(
                await repository.list_interaction_modes(lock=lock), key=lambda x: x.key
            )
        )
        system = await self._prompt_state(
            repository,
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            SystemPrompt,
            lock,
        )
        profile_values = []
        for item in profiles:
            profile_values.append(
                ProfileConfiguration(
                    key=item.key,
                    name=item.name,
                    description=item.description,
                    status=item.status,
                    prompt=await self._prompt_state(
                        repository,
                        ComponentAddress(
                            ComponentKind("ProfilePrompt"), ProfileScope(item.key)
                        ),
                        ProfilePrompt,
                        lock,
                    ),
                )
            )
        mode_values = []
        for item in modes:
            mode_values.append(
                InteractionModeConfiguration(
                    key=item.key,
                    name=item.name,
                    description=item.description,
                    status=item.status,
                    prompt=await self._prompt_state(
                        repository,
                        ComponentAddress(
                            ComponentKind("InteractionPrompt"),
                            InteractionModeScope(item.key),
                        ),
                        InteractionPrompt,
                        lock,
                    ),
                )
            )
        has_drafts = bool(
            system.draft
            or any(item.prompt.draft for item in profile_values)
            or any(item.prompt.draft for item in mode_values)
        )
        return PlatformConfiguration(
            system_prompt=system,
            profiles=tuple(profile_values),
            interaction_modes=tuple(mode_values),
            status=ConfigurationStatus(has_drafts=has_drafts, publishable=has_drafts),
        )

    async def _prompt_state(self, repository, address, value_type, lock):
        exists, draft, active = await repository.get_component(address, lock=lock)
        if not exists:
            return PromptState[value_type]()
        definition = self._registry.resolve(address)
        return PromptState[value_type](
            active=definition.deserialize(active.value) if active else None,
            draft=definition.deserialize(draft.value) if draft else None,
        )

    def _plan(self, current, desired):
        errors: list[ValidationIssue] = []
        for path, address, value in self._desired_prompts(desired):
            try:
                definition = self._registry.resolve(address)
                definition.deserialize(value.model_dump(mode="json"))
            except ComponentError as error:
                errors.append(ValidationIssue(error.code, path, str(error)))
        desired_profiles = {item.key for item in desired.profiles}
        desired_modes = {item.key for item in desired.interaction_modes}
        for label, entries, keys in (
            ("profiles", current.profiles, desired_profiles),
            ("interaction_modes", current.interaction_modes, desired_modes),
        ):
            for item in entries:
                if item.key not in keys:
                    errors.append(
                        ValidationIssue(
                            "catalog_entry_removal_unsupported",
                            f"{label}.{item.key}",
                            f"{label[:-1].replace('_', ' ')} removal is not defined by the frozen contract",
                        )
                    )
        catalog_changes = []
        for label, entries, current_entries in (
            ("profiles", desired.profiles, current.profiles),
            ("interaction_modes", desired.interaction_modes, current.interaction_modes),
        ):
            current_by_key = {item.key: item for item in current_entries}
            for item in entries:
                before = current_by_key.get(item.key)
                if before is None or _catalog_value(before) != _catalog_value(item):
                    catalog_changes.append(
                        ConfigurationChange(
                            f"{label}.{item.key}",
                            "create" if before is None else "update",
                            "immediate",
                        )
                    )
        states = {"system_prompt": current.system_prompt}
        states.update(
            {f"profiles.{item.key}.prompt": item.prompt for item in current.profiles}
        )
        states.update(
            {
                f"interaction_modes.{item.key}.prompt": item.prompt
                for item in current.interaction_modes
            }
        )
        draft_changes = []
        for path, _, value in self._desired_prompts(desired):
            state = states.get(path, PromptState())
            payload = value.model_dump(mode="json")
            active = state.active.model_dump(mode="json") if state.active else None
            draft = state.draft.model_dump(mode="json") if state.draft else None
            operation = (
                "clear"
                if draft is not None and active == payload
                else "create"
                if draft is None and active != payload
                else "update"
                if draft is not None and draft != payload
                else None
            )
            if operation:
                draft_changes.append(ConfigurationChange(path, operation, "draft"))
        return PlatformConfigurationPlan(
            not errors, tuple(catalog_changes), tuple(draft_changes), (), tuple(errors)
        )

    @staticmethod
    def _desired_prompts(desired):
        yield (
            "system_prompt",
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            desired.system_prompt,
        )
        for item in desired.profiles:
            yield (
                f"profiles.{item.key}.prompt",
                ComponentAddress(
                    ComponentKind("ProfilePrompt"), ProfileScope(item.key)
                ),
                item.prompt,
            )
        for item in desired.interaction_modes:
            yield (
                f"interaction_modes.{item.key}.prompt",
                ComponentAddress(
                    ComponentKind("InteractionPrompt"), InteractionModeScope(item.key)
                ),
                item.prompt,
            )

    @staticmethod
    def _current_prompt_addresses(configuration):
        yield (
            "system_prompt",
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
        )
        for item in configuration.profiles:
            yield (
                f"profiles.{item.key}.prompt",
                ComponentAddress(
                    ComponentKind("ProfilePrompt"), ProfileScope(item.key)
                ),
            )
        for item in configuration.interaction_modes:
            yield (
                f"interaction_modes.{item.key}.prompt",
                ComponentAddress(
                    ComponentKind("InteractionPrompt"), InteractionModeScope(item.key)
                ),
            )

    @staticmethod
    def _all_paths(desired):
        yield "system_prompt"
        for item in desired.profiles:
            yield f"profiles.{item.key}"
            yield f"profiles.{item.key}.prompt"
        for item in desired.interaction_modes:
            yield f"interaction_modes.{item.key}"
            yield f"interaction_modes.{item.key}.prompt"

    @staticmethod
    def _apply_result(result):
        return {
            "catalogs_updated": list(result.catalogs_updated),
            "drafts_saved": list(result.drafts_saved),
            "unchanged": list(result.unchanged),
            "configuration": result.configuration.model_dump(mode="json"),
        }

    @staticmethod
    def _publish_result(result):
        return {
            "published_components": list(result.published_components),
            "unchanged_components": list(result.unchanged_components),
            "configuration": result.configuration.model_dump(mode="json"),
        }

    @staticmethod
    def _check_replay(replay: StoredReplay, fingerprint: str):
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        return replay.logical_result

    @classmethod
    def _replay_apply(cls, replay, fingerprint):
        value = cls._check_replay(replay, fingerprint)
        return PlatformConfigurationApplyResult(
            tuple(value["catalogs_updated"]),
            tuple(value["drafts_saved"]),
            tuple(value["unchanged"]),
            PlatformConfiguration.model_validate(value["configuration"]),
        )

    @classmethod
    def _replay_publish(cls, replay, fingerprint):
        value = cls._check_replay(replay, fingerprint)
        return PlatformConfigurationPublishResult(
            tuple(value["published_components"]),
            tuple(value["unchanged_components"]),
            PlatformConfiguration.model_validate(value["configuration"]),
        )


def _catalog_value(value) -> tuple[str, str, str, CatalogStatus]:
    return value.key, value.name, value.description, value.status
