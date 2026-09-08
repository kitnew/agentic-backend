from dataclasses import dataclass
from typing import Any

from contracts import ValidationIssue
from pydantic import BaseModel, ConfigDict

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.transactions import SystemConfigurationCommandScope
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    SystemScope,
)
from control_plane.domain.frozen_components import (
    LLMDefaults,
    Policies,
    RealtimeDefaults,
    STTDefaults,
    TTSDefaults,
)
from control_plane.domain.live_components import LiveComponentState
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.managed_resources import (
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    ModelDeploymentRef,
    PlatformCredentialScope,
    RealtimeCapabilities,
)

_FIELDS = (
    "stt_defaults",
    "llm_defaults",
    "tts_defaults",
    "realtime_defaults",
    "policies",
)
_KINDS = {
    "stt_defaults": "STTDefaults",
    "llm_defaults": "LLMDefaults",
    "tts_defaults": "TTSDefaults",
    "realtime_defaults": "RealtimeDefaults",
    "policies": "Policies",
}


class SystemConfigurationDesired(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stt_defaults: STTDefaults
    llm_defaults: LLMDefaults
    tts_defaults: TTSDefaults
    realtime_defaults: RealtimeDefaults
    policies: Policies


class SystemConfiguration(SystemConfigurationDesired):
    pass


@dataclass(frozen=True, slots=True)
class ConfigurationChange:
    path: str
    operation: str
    activation: str = "immediate"


@dataclass(frozen=True, slots=True)
class SystemConfigurationPlan:
    valid: bool
    changes: tuple[ConfigurationChange, ...]
    warnings: tuple[str, ...]
    errors: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class SystemConfigurationApplyResult:
    updated: tuple[str, ...]
    unchanged: tuple[str, ...]
    configuration: SystemConfiguration


class SystemConfigurationError(Exception):
    code = "configuration_invalid"


class SystemConfigurationNotFound(SystemConfigurationError):
    code = "system_configuration_not_found"


class SystemConfigurationPreconditionFailed(SystemConfigurationError):
    code = "precondition_failed"


class SystemConfigurationService:
    def __init__(
        self,
        registry: ComponentDefinitionRegistry,
        command_scope: SystemConfigurationCommandScope,
    ) -> None:
        self._registry = registry
        self._command_scope = command_scope

    async def get(self) -> SystemConfiguration:
        async with self._command_scope() as (repository, _):
            values = await self._load(repository)
        configuration = self._configuration(values)
        if configuration is None:
            raise SystemConfigurationNotFound("system configuration is incomplete")
        return configuration

    async def plan(
        self, desired: SystemConfigurationDesired
    ) -> SystemConfigurationPlan:
        async with self._command_scope() as (repository, _):
            current = await self._load(repository)
            errors = await self._validate(repository, desired)
        return SystemConfigurationPlan(
            not errors,
            tuple(
                ConfigurationChange(
                    field, "create" if current[field] is None else "update"
                )
                for field in _FIELDS
                if not self._same(current[field], getattr(desired, field))
            ),
            (),
            tuple(errors),
        )

    async def apply(
        self,
        desired: SystemConfigurationDesired,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> SystemConfigurationApplyResult:
        payload = desired.model_dump(mode="json")
        fingerprint = request_fingerprint(
            {"desired": payload, "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "system_configuration.apply", idempotency_key
            )
            if replay is not None:
                return self._replay(replay, fingerprint)
            current = await self._load(repository, lock=True)
            configuration = self._configuration(current)
            if (
                configuration is None and expected_token != self.concurrency_token(None)
            ) or (
                configuration is not None
                and expected_token != self.concurrency_token(configuration)
            ):
                raise SystemConfigurationPreconditionFailed(
                    "system configuration precondition failed"
                )
            errors = await self._validate(repository, desired, lock=True)
            if errors:
                raise SystemConfigurationError(errors[0].message)
            updated = tuple(
                field
                for field in _FIELDS
                if not self._same(current[field], getattr(desired, field))
            )
            for field in updated:
                definition = self._registry.resolve(self._address(field))
                await repository.set(
                    self._address(field),
                    getattr(desired, field).model_dump(mode="json"),
                    definition.schema_version,
                    principal,
                )
            result = SystemConfigurationApplyResult(
                updated,
                tuple(field for field in _FIELDS if field not in updated),
                SystemConfiguration.model_validate(payload),
            )
            await replays.add(
                principal,
                "system_configuration.apply",
                idempotency_key,
                fingerprint,
                self._result(result),
            )
        return result

    @staticmethod
    def concurrency_token(configuration: SystemConfiguration | None) -> str:
        if configuration is None:
            return "*"
        return opaque_concurrency_token(configuration.model_dump(mode="json"))

    async def _load(self, repository, *, lock=False):
        return {
            field: await repository.get(self._address(field), lock=lock)
            for field in _FIELDS
        }

    @staticmethod
    def _address(field: str) -> ComponentAddress:
        return ComponentAddress(ComponentKind(_KINDS[field]), SystemScope())

    @staticmethod
    def _configuration(values) -> SystemConfiguration | None:
        if any(value is None for value in values.values()):
            return None
        return SystemConfiguration(**{field: values[field].value for field in _FIELDS})

    @staticmethod
    def _same(state: LiveComponentState[Any] | None, desired: BaseModel) -> bool:
        return state is not None and state.value == desired.model_dump(mode="json")

    async def _validate(self, repository, desired, *, lock=False):
        issues: list[ValidationIssue] = []
        await self._deployment(
            repository,
            desired.stt_defaults.deployment_ref,
            DeploymentKind.STT,
            "stt_defaults.deployment_ref",
            issues,
            lock,
            capability="supports_cascade",
        )
        llm = await self._deployment(
            repository,
            desired.llm_defaults.deployment_ref,
            DeploymentKind.LLM,
            "llm_defaults.deployment_ref",
            issues,
            lock,
        )
        await self._deployment(
            repository,
            desired.tts_defaults.deployment_ref,
            DeploymentKind.TTS,
            "tts_defaults.deployment_ref",
            issues,
            lock,
        )
        realtime = await self._deployment(
            repository,
            desired.realtime_defaults.deployment_ref,
            DeploymentKind.REALTIME,
            "realtime_defaults.deployment_ref",
            issues,
            lock,
        )
        await self._deployment(
            repository,
            desired.realtime_defaults.input_transcription.deployment_ref,
            DeploymentKind.STT,
            "realtime_defaults.input_transcription.deployment_ref",
            issues,
            lock,
            capability="supports_realtime_input_transcription",
        )
        if llm and isinstance(llm.capabilities, LLMCapabilities):
            if (
                desired.llm_defaults.temperature is not None
                and not llm.capabilities.supports_temperature
            ):
                issues.append(
                    ValidationIssue(
                        "unsupported_capability",
                        "llm_defaults.temperature",
                        "deployment does not support temperature",
                    )
                )
            if (
                desired.llm_defaults.reasoning_effort is not None
                and not llm.capabilities.supports_reasoning_effort
            ):
                issues.append(
                    ValidationIssue(
                        "unsupported_capability",
                        "llm_defaults.reasoning_effort",
                        "deployment does not support reasoning_effort",
                    )
                )
        if realtime and isinstance(realtime.capabilities, RealtimeCapabilities):
            strategy = desired.realtime_defaults.turn_completion.strategy
            supported = (
                realtime.capabilities.supports_server_vad
                if strategy == "server_vad"
                else realtime.capabilities.supports_semantic_vad
            )
            if not supported:
                issues.append(
                    ValidationIssue(
                        "unsupported_capability",
                        "realtime_defaults.turn_completion",
                        f"deployment does not support {strategy}",
                    )
                )
        return issues

    async def validate_live_component(self, repository, address, value) -> None:
        issues: list[ValidationIssue] = []
        kind = str(address.kind)
        if kind == "STTDefaults":
            await self._deployment(
                repository,
                value.deployment_ref,
                DeploymentKind.STT,
                "value.deployment_ref",
                issues,
                True,
                capability="supports_cascade",
            )
        elif kind == "LLMDefaults":
            deployment = await self._deployment(
                repository,
                value.deployment_ref,
                DeploymentKind.LLM,
                "value.deployment_ref",
                issues,
                True,
            )
            if deployment and isinstance(deployment.capabilities, LLMCapabilities):
                if (
                    value.temperature is not None
                    and not deployment.capabilities.supports_temperature
                ):
                    issues.append(
                        ValidationIssue(
                            "unsupported_capability",
                            "value.temperature",
                            "deployment does not support temperature",
                        )
                    )
                if (
                    value.reasoning_effort is not None
                    and not deployment.capabilities.supports_reasoning_effort
                ):
                    issues.append(
                        ValidationIssue(
                            "unsupported_capability",
                            "value.reasoning_effort",
                            "deployment does not support reasoning_effort",
                        )
                    )
        elif kind == "TTSDefaults":
            await self._deployment(
                repository,
                value.deployment_ref,
                DeploymentKind.TTS,
                "value.deployment_ref",
                issues,
                True,
            )
        elif kind == "RealtimeDefaults":
            deployment = await self._deployment(
                repository,
                value.deployment_ref,
                DeploymentKind.REALTIME,
                "value.deployment_ref",
                issues,
                True,
            )
            await self._deployment(
                repository,
                value.input_transcription.deployment_ref,
                DeploymentKind.STT,
                "value.input_transcription.deployment_ref",
                issues,
                True,
                capability="supports_realtime_input_transcription",
            )
            if deployment and isinstance(deployment.capabilities, RealtimeCapabilities):
                strategy = value.turn_completion.strategy
                supported = (
                    deployment.capabilities.supports_server_vad
                    if strategy == "server_vad"
                    else deployment.capabilities.supports_semantic_vad
                )
                if not supported:
                    issues.append(
                        ValidationIssue(
                            "unsupported_capability",
                            "value.turn_completion",
                            f"deployment does not support {strategy}",
                        )
                    )
        if issues:
            raise SystemConfigurationError(issues[0].message)

    async def _deployment(
        self, repository, ref, expected, path, issues, lock, *, capability=None
    ):
        try:
            deployment = await repository.get_deployment(
                ModelDeploymentRef(ref), lock=lock
            )
        except ManagedResourceNotFound, KeyError:
            issues.append(
                ValidationIssue(
                    "missing_deployment", path, "referenced deployment does not exist"
                )
            )
            return None
        if deployment.deployment_kind is not expected:
            issues.append(
                ValidationIssue(
                    "wrong_deployment_kind",
                    path,
                    f"deployment must have deployment_kind={expected.value}",
                )
            )
            return deployment
        if not deployment.enabled:
            issues.append(
                ValidationIssue("deployment_unusable", path, "deployment is disabled")
            )
        try:
            connection = await repository.get_connection(
                deployment.connection_ref, lock=lock
            )
            credential = await repository.get_credential(
                connection.credential_ref, lock=lock
            )
            if (
                not connection.enabled
                or credential.status is CredentialStatus.REVOKED
                or not isinstance(credential.scope, PlatformCredentialScope)
            ):
                issues.append(
                    ValidationIssue(
                        "deployment_unusable",
                        path,
                        "deployment provider connection is unusable",
                    )
                )
        except ManagedResourceNotFound, KeyError:
            issues.append(
                ValidationIssue(
                    "deployment_unusable",
                    path,
                    "deployment provider graph is incomplete",
                )
            )
        if capability and not getattr(deployment.capabilities, capability, False):
            issues.append(
                ValidationIssue(
                    "unsupported_capability",
                    path,
                    f"deployment does not support {capability}",
                )
            )
        return deployment

    @staticmethod
    def _result(result):
        return {
            "updated": list(result.updated),
            "unchanged": list(result.unchanged),
            "configuration": result.configuration.model_dump(mode="json"),
        }

    @staticmethod
    def _replay(replay: StoredReplay, fingerprint: str):
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        value = replay.logical_result
        return SystemConfigurationApplyResult(
            tuple(value["updated"]),
            tuple(value["unchanged"]),
            SystemConfiguration.model_validate(value["configuration"]),
        )
