from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.platform_configuration import (
    ConfigurationStatus,
    PromptState,
)
from control_plane.application.ports.transactions import (
    TenantConfigurationCommandScope,
)
from control_plane.application.system_configuration import (
    ConfigurationChange,
    ValidationIssue,
)
from control_plane.domain.catalogs import CatalogStatus
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.frozen_components import (
    ActionsAvailability,
    ActionsDefinition,
    AgentPersonality,
    Architecture,
    BusinessInfo,
    Knowledge,
    ProfileReference,
    RuntimeOverrides,
    TenantPrompt,
)
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.registries import ArchitectureRegistry, UnknownRegistryKey

_VERSIONED = (
    ("tenant_prompt", "TenantPrompt", TenantPrompt),
    ("knowledge", "Knowledge", Knowledge),
    ("agent_personality", "AgentPersonality", AgentPersonality),
    ("business_info", "BusinessInfo", BusinessInfo),
    ("actions_definition", "ActionsDefinition", ActionsDefinition),
)
_LIVE = (
    ("architecture", "Architecture", Architecture),
    ("profile_reference", "ProfileReference", ProfileReference),
    ("runtime_overrides", "RuntimeOverrides", RuntimeOverrides),
    ("actions_availability", "ActionsAvailability", ActionsAvailability),
)


class TenantConfigurationDesired(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_prompt: TenantPrompt
    knowledge: Knowledge
    agent_personality: AgentPersonality
    business_info: BusinessInfo
    actions_definition: ActionsDefinition
    architecture: Architecture
    profile_reference: ProfileReference
    runtime_overrides: RuntimeOverrides
    actions_availability: ActionsAvailability


class TenantVersionedConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_prompt: PromptState[TenantPrompt]
    knowledge: PromptState[Knowledge]
    agent_personality: PromptState[AgentPersonality]
    business_info: PromptState[BusinessInfo]
    actions_definition: PromptState[ActionsDefinition]


class TenantLiveConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: Architecture
    profile_reference: ProfileReference
    runtime_overrides: RuntimeOverrides
    actions_availability: ActionsAvailability


class TenantConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    versioned: TenantVersionedConfiguration
    live: TenantLiveConfiguration
    status: ConfigurationStatus


@dataclass(frozen=True, slots=True)
class TenantConfigurationChanges:
    immediate: tuple[ConfigurationChange, ...]
    draft: tuple[ConfigurationChange, ...]


@dataclass(frozen=True, slots=True)
class TenantConfigurationPlan:
    valid: bool
    changes: TenantConfigurationChanges
    warnings: tuple[str, ...]
    errors: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class TenantConfigurationApplyResult:
    live_updated: tuple[str, ...]
    drafts_saved: tuple[str, ...]
    unchanged: tuple[str, ...]
    configuration: TenantConfiguration


@dataclass(frozen=True, slots=True)
class TenantConfigurationPublishResult:
    published_components: tuple[str, ...]
    unchanged_components: tuple[str, ...]
    configuration: TenantConfiguration


class TenantConfigurationError(Exception):
    code = "configuration_invalid"


class TenantConfigurationNotFound(TenantConfigurationError):
    code = "tenant_configuration_not_found"


class TenantConfigurationPreconditionFailed(TenantConfigurationError):
    code = "precondition_failed"


@dataclass(slots=True)
class _LoadedTenantConfiguration:
    tenant_id: str
    versioned: dict[str, PromptState[Any]]
    live: dict[str, Any | None]

    @property
    def has_drafts(self) -> bool:
        return any(value.draft is not None for value in self.versioned.values())

    @property
    def initial(self) -> bool:
        return (
            not self.has_drafts
            and all(value.active is None for value in self.versioned.values())
            and all(value is None for value in self.live.values())
        )


class TenantConfigurationService:
    def __init__(
        self,
        registry: ComponentDefinitionRegistry,
        architectures: ArchitectureRegistry,
        command_scope: TenantConfigurationCommandScope,
    ) -> None:
        self._registry = registry
        self._architectures = architectures
        self._command_scope = command_scope

    async def get(self, tenant_id: str) -> TenantConfiguration:
        async with self._command_scope(tenant_id) as (repository, _):
            current = await self._load(repository, tenant_id)
        return self._configuration(current)

    async def validate_live_component(self, repository, address, value) -> None:
        tenant_id = address.scope.key
        if tenant_id is None:
            raise TenantConfigurationError("tenant scope is required")
        if isinstance(value, Architecture):
            try:
                self._architectures.resolve(value.architecture_key)
            except UnknownRegistryKey as error:
                raise TenantConfigurationError(str(error)) from error
        elif isinstance(value, ProfileReference):
            profile = await repository.get_profile(value.profile_key, lock=True)
            if profile is None or profile.status is not CatalogStatus.ENABLED:
                raise TenantConfigurationError(
                    "referenced profile does not exist or is disabled"
                )
            _, _, prompt = await repository.get_component(
                ComponentAddress(
                    ComponentKind("ProfilePrompt"), ProfileScope(profile.key)
                ),
                lock=True,
            )
            if prompt is None:
                raise TenantConfigurationError(
                    "referenced profile has no active prompt"
                )
        elif isinstance(value, ActionsAvailability):
            _, _, active = await repository.get_component(
                self._address(tenant_id, "actions_definition"), lock=True
            )
            known = (
                set(
                    self._registry.resolve(
                        self._address(tenant_id, "actions_definition")
                    )
                    .deserialize(active.value)
                    .actions
                )
                if active is not None
                else set()
            )
            if unknown := set(value.actions) - known:
                raise TenantConfigurationError(
                    f"unknown actions: {', '.join(sorted(unknown))}"
                )

    async def plan(
        self, tenant_id: str, desired: TenantConfigurationDesired
    ) -> TenantConfigurationPlan:
        async with self._command_scope(tenant_id) as (repository, _):
            current = await self._load(repository, tenant_id)
            return await self._plan(repository, current, desired)

    async def apply(
        self,
        tenant_id: str,
        desired: TenantConfigurationDesired,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> TenantConfigurationApplyResult:
        fingerprint = request_fingerprint(
            {
                "tenant_id": tenant_id,
                "desired": desired.model_dump(mode="json"),
                "if_match": expected_token,
            }
        )
        async with self._command_scope(tenant_id) as (repository, replays):
            replay = await replays.get(
                principal, "tenant_configuration.apply", idempotency_key
            )
            if replay is not None:
                return self._replay_apply(replay, fingerprint)
            current = await self._load(repository, tenant_id, lock=True)
            self._require_token(current, expected_token)
            plan = await self._plan(repository, current, desired, lock=True)
            if plan.errors:
                raise TenantConfigurationError(plan.errors[0].message)

            live_updated: list[str] = []
            for field, _, _ in _LIVE:
                value = getattr(desired, field)
                if self._same(current.live[field], value):
                    continue
                definition = self._registry.resolve(self._address(tenant_id, field))
                await repository.set_live(
                    self._address(tenant_id, field),
                    definition.serialize(value),
                    definition.schema_version,
                    principal,
                )
                live_updated.append(field)

            drafts_saved: list[str] = []
            for field, _, _ in _VERSIONED:
                value = getattr(desired, field)
                state = current.versioned[field]
                payload = value.model_dump(mode="json", by_alias=True)
                active = (
                    state.active.model_dump(mode="json", by_alias=True)
                    if state.active is not None
                    else None
                )
                draft = (
                    state.draft.model_dump(mode="json", by_alias=True)
                    if state.draft is not None
                    else None
                )
                address = self._address(tenant_id, field)
                _, stored_draft, stored_active = await repository.get_component(
                    address, lock=True
                )
                if draft == payload:
                    continue
                if active == payload:
                    if stored_draft is not None:
                        await repository.discard_draft(address, stored_draft.version)
                        drafts_saved.append(field)
                    continue
                definition = self._registry.resolve(address)
                await repository.save_draft(
                    address,
                    payload,
                    definition.schema_version,
                    stored_draft.version if stored_draft else None,
                    stored_active.id if stored_active else None,
                    principal,
                )
                drafts_saved.append(field)

            configuration = self._configuration(await self._load(repository, tenant_id))
            changed = set(live_updated) | set(drafts_saved)
            result = TenantConfigurationApplyResult(
                tuple(live_updated),
                tuple(drafts_saved),
                tuple(field for field in self._all_fields() if field not in changed),
                configuration,
            )
            await replays.add(
                principal,
                "tenant_configuration.apply",
                idempotency_key,
                fingerprint,
                self._apply_result(result),
            )
            return result

    async def publish(
        self,
        tenant_id: str,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> TenantConfigurationPublishResult:
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "if_match": expected_token}
        )
        async with self._command_scope(tenant_id) as (repository, replays):
            replay = await replays.get(
                principal, "tenant_configuration.publish", idempotency_key
            )
            if replay is not None:
                return self._replay_publish(replay, fingerprint)
            current = await self._load(repository, tenant_id, lock=True)
            self._require_token(current, expected_token)
            self._configuration(current)
            final_actions_state = current.versioned["actions_definition"]
            final_actions = final_actions_state.draft or final_actions_state.active
            availability = current.live["actions_availability"]
            assert isinstance(availability, ActionsAvailability)
            known = (
                set(final_actions.actions)
                if isinstance(final_actions, ActionsDefinition)
                else set()
            )
            if unknown := set(availability.actions) - known:
                raise TenantConfigurationError(
                    "published ActionsDefinition would invalidate ActionsAvailability: "
                    + ", ".join(sorted(unknown))
                )
            published: list[str] = []
            unchanged: list[str] = []
            for field, _, _ in _VERSIONED:
                address = self._address(tenant_id, field)
                _, draft, _ = await repository.get_component(address, lock=True)
                if draft is None:
                    unchanged.append(field)
                    continue
                definition = self._registry.resolve(address)
                value = definition.deserialize(draft.value)
                if isinstance(value, ActionsDefinition):
                    errors: list[ValidationIssue] = []
                    await self._validate_integrations(
                        repository, tenant_id, value, errors, lock=True
                    )
                    if errors:
                        raise TenantConfigurationError(errors[0].message)
                await repository.publish_draft(
                    address, draft.version, principal, definition
                )
                published.append(field)
            configuration = self._configuration(await self._load(repository, tenant_id))
            result = TenantConfigurationPublishResult(
                tuple(published), tuple(unchanged), configuration
            )
            await replays.add(
                principal,
                "tenant_configuration.publish",
                idempotency_key,
                fingerprint,
                self._publish_result(result),
            )
            return result

    @classmethod
    def concurrency_token(
        cls, configuration: TenantConfiguration | _LoadedTenantConfiguration | None
    ) -> str:
        if configuration is None or (
            isinstance(configuration, _LoadedTenantConfiguration)
            and configuration.initial
        ):
            return "*"
        if isinstance(configuration, TenantConfiguration):
            payload = configuration.model_dump(mode="json")
        else:
            payload = cls._state_payload(configuration)
        return opaque_concurrency_token(payload)

    async def _load(self, repository, tenant_id: str, *, lock=False):
        versioned: dict[str, PromptState[Any]] = {}
        for field, _, _ in _VERSIONED:
            address = self._address(tenant_id, field)
            exists, draft, active = await repository.get_component(address, lock=lock)
            if not exists:
                versioned[field] = PromptState()
                continue
            definition = self._registry.resolve(address)
            versioned[field] = PromptState(
                active=definition.deserialize(active.value) if active else None,
                draft=definition.deserialize(draft.value) if draft else None,
            )
        live: dict[str, Any | None] = {}
        for field, _, _ in _LIVE:
            address = self._address(tenant_id, field)
            state = await repository.get_live(address, lock=lock)
            live[field] = (
                self._registry.resolve(address).deserialize(state.value)
                if state is not None
                else None
            )
        return _LoadedTenantConfiguration(tenant_id, versioned, live)

    def _configuration(
        self, current: _LoadedTenantConfiguration
    ) -> TenantConfiguration:
        if any(value is None for value in current.live.values()):
            raise TenantConfigurationNotFound("tenant configuration is incomplete")
        return TenantConfiguration(
            tenant_id=current.tenant_id,
            versioned=TenantVersionedConfiguration(**current.versioned),
            live=TenantLiveConfiguration(
                architecture=cast(Architecture, current.live["architecture"]),
                profile_reference=cast(
                    ProfileReference, current.live["profile_reference"]
                ),
                runtime_overrides=cast(
                    RuntimeOverrides, current.live["runtime_overrides"]
                ),
                actions_availability=cast(
                    ActionsAvailability, current.live["actions_availability"]
                ),
            ),
            status=ConfigurationStatus(
                has_drafts=current.has_drafts, publishable=current.has_drafts
            ),
        )

    async def _plan(self, repository, current, desired, *, lock=False):
        errors: list[ValidationIssue] = []
        for field, _, _ in (*_VERSIONED, *_LIVE):
            address = self._address(current.tenant_id, field)
            try:
                value = getattr(desired, field)
                self._registry.resolve(address).deserialize(self._serialize(value))
            except (ComponentError, ValueError) as error:
                errors.append(ValidationIssue("invalid_component", field, str(error)))

        try:
            self._architectures.resolve(desired.architecture.architecture_key)
        except UnknownRegistryKey as error:
            errors.append(
                ValidationIssue("unknown_architecture", "architecture", str(error))
            )

        profile = await repository.get_profile(
            desired.profile_reference.profile_key, lock=lock
        )
        if profile is None or profile.status is not CatalogStatus.ENABLED:
            errors.append(
                ValidationIssue(
                    "unknown_or_disabled_profile",
                    "profile_reference",
                    "referenced profile does not exist or is disabled",
                )
            )
        else:
            _, _, prompt = await repository.get_component(
                ComponentAddress(
                    ComponentKind("ProfilePrompt"), ProfileScope(profile.key)
                ),
                lock=lock,
            )
            if prompt is None:
                errors.append(
                    ValidationIssue(
                        "profile_prompt_not_published",
                        "profile_reference",
                        "referenced profile has no active prompt",
                    )
                )

        await self._validate_integrations(
            repository,
            current.tenant_id,
            desired.actions_definition,
            errors,
            lock=lock,
        )

        # Availability is live; a same-apply ActionsDefinition draft is not effective.
        effective = current.versioned["actions_definition"].active
        known = (
            set(effective.actions)
            if isinstance(effective, ActionsDefinition)
            else set()
        )
        for key in desired.actions_availability.actions:
            if key not in known:
                errors.append(
                    ValidationIssue(
                        "unknown_action",
                        f"actions_availability.actions.{key}",
                        f"action {key} is not in the effective published ActionsDefinition",
                    )
                )

        immediate = tuple(
            ConfigurationChange(
                field,
                "create" if current.live[field] is None else "update",
                "immediate",
            )
            for field, _, _ in _LIVE
            if not self._same(current.live[field], getattr(desired, field))
        )
        draft = tuple(
            ConfigurationChange(field, operation, "draft")
            for field, _, _ in _VERSIONED
            if (
                operation := self._draft_operation(
                    current.versioned[field], getattr(desired, field)
                )
            )
        )
        return TenantConfigurationPlan(
            not errors,
            TenantConfigurationChanges(immediate, draft),
            (),
            tuple(errors),
        )

    async def _validate_integrations(
        self,
        repository,
        tenant_id,
        value: ActionsDefinition,
        errors,
        *,
        lock: bool = False,
    ) -> None:
        for key in sorted(
            {action.execution.integration_key for action in value.actions.values()}
        ):
            try:
                await repository.get_integration_by_key(tenant_id, key, lock=lock)
            except ManagedResourceNotFound:
                errors.append(
                    ValidationIssue(
                        "unknown_integration",
                        "actions_definition",
                        f"integration_key {key} does not belong to tenant",
                    )
                )

    def _require_token(self, current, expected_token):
        if self.concurrency_token(current) != expected_token:
            raise TenantConfigurationPreconditionFailed(
                "tenant configuration precondition failed"
            )

    @staticmethod
    def _draft_operation(state, desired):
        payload = desired.model_dump(mode="json", by_alias=True)
        active = (
            state.active.model_dump(mode="json", by_alias=True)
            if state.active is not None
            else None
        )
        draft = (
            state.draft.model_dump(mode="json", by_alias=True)
            if state.draft is not None
            else None
        )
        if draft is not None and active == payload:
            return "clear"
        if draft is None and active != payload:
            return "create"
        if draft is not None and draft != payload:
            return "update"
        return None

    @staticmethod
    def _same(current, desired) -> bool:
        return current is not None and TenantConfigurationService._serialize(
            current
        ) == TenantConfigurationService._serialize(desired)

    @staticmethod
    def _serialize(value):
        return (
            value.model_dump(mode="json", by_alias=True)
            if isinstance(value, BaseModel)
            else value
        )

    @staticmethod
    def _address(tenant_id: str, field: str) -> ComponentAddress:
        kinds = {name: kind for name, kind, _ in (*_VERSIONED, *_LIVE)}
        return ComponentAddress(ComponentKind(kinds[field]), TenantScope(tenant_id))

    @staticmethod
    def _all_fields():
        return tuple(field for field, _, _ in (*_VERSIONED, *_LIVE))

    @staticmethod
    def _state_payload(current):
        return {
            "tenant_id": current.tenant_id,
            "versioned": {
                field: state.model_dump(mode="json")
                for field, state in current.versioned.items()
            },
            "live": {
                field: TenantConfigurationService._serialize(value)
                for field, value in current.live.items()
            },
            "status": {
                "has_drafts": current.has_drafts,
                "publishable": current.has_drafts,
            },
        }

    @staticmethod
    def _apply_result(result):
        return {
            "live_updated": list(result.live_updated),
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
        return TenantConfigurationApplyResult(
            tuple(value["live_updated"]),
            tuple(value["drafts_saved"]),
            tuple(value["unchanged"]),
            TenantConfiguration.model_validate(value["configuration"]),
        )

    @classmethod
    def _replay_publish(cls, replay, fingerprint):
        value = cls._check_replay(replay, fingerprint)
        return TenantConfigurationPublishResult(
            tuple(value["published_components"]),
            tuple(value["unchanged_components"]),
            TenantConfiguration.model_validate(value["configuration"]),
        )
