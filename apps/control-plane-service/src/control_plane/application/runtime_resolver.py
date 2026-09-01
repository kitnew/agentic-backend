from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol, cast
from uuid import UUID

from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import (
    Credential,
    CredentialStatus,
    DeploymentKind,
    ModelDeployment,
    ProviderConnection,
)
from control_plane.domain.providers import ProviderRegistry
from control_plane.domain.runtime_components import (
    ArchitectureKind,
    ArchitecturePolicy,
    CascadeExecutionDefaults,
    LLMDefaults,
    ProviderVADCommitPolicy,
    RealtimeExecutionDefaults,
    ServerVADTurnCompletion,
    SpeechOverrides,
    STTDefaults,
    TTSDefaults,
)
from control_plane.domain.runtime_resolution import (
    CandidateAttempt,
    CandidateFailure,
    ComponentProvenance,
    CredentialProvenance,
    ResolutionFailureReason,
    ResolvedCascadeExecution,
    ResolvedCascadeLLM,
    ResolvedCascadeRuntime,
    ResolvedCascadeSTT,
    ResolvedCascadeTTS,
    ResolvedKeyterms,
    ResolvedProviderResource,
    ResolvedRealtimeModel,
    ResolvedRealtimeRuntime,
    ResolvedRealtimeTranscription,
    ResolvedRuntime,
    ResolvedSpeechHints,
    RuntimeResolution,
    RuntimeResolutionError,
    SpeechHintStatus,
)


@dataclass(frozen=True, slots=True)
class StoredActiveRuntimeComponent:
    address: ComponentAddress
    revision_id: UUID
    revision_number: int
    schema_version: int
    value: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _ActiveRuntimeComponent[T]:
    address: ComponentAddress
    revision_id: UUID
    revision_number: int
    schema_version: int
    value: T


@dataclass(frozen=True, slots=True)
class RuntimeResolutionState:
    components: Mapping[ComponentAddress, StoredActiveRuntimeComponent]
    deployments: Mapping[UUID, ModelDeployment]
    connections: Mapping[UUID, ProviderConnection]
    credentials: Mapping[UUID, Credential]


class RuntimeResolutionReader(Protocol):
    async def load(self, tenant_id: str) -> RuntimeResolutionState: ...


class _CandidateRejected(Exception):
    def __init__(
        self, reason: ResolutionFailureReason, details: Mapping[str, object]
    ) -> None:
        self.reason = reason
        self.details = details


class RuntimeResolver:
    def __init__(
        self,
        registry: ComponentRegistry,
        providers: ProviderRegistry,
        reader: RuntimeResolutionReader,
    ) -> None:
        self._registry = registry
        self._providers = providers
        self._reader = reader

    async def resolve_runtime(self, tenant_id: str) -> RuntimeResolution:
        state = await self._reader.load(tenant_id)
        policy = self._required_tenant(
            state, tenant_id, "runtime.architecture.policy", ArchitecturePolicy
        )
        speech = self._required_tenant(
            state, tenant_id, "runtime.speech.overrides", SpeechOverrides
        )
        attempts: list[CandidateAttempt] = []
        for architecture in policy.value.architectures:
            try:
                selected = self._resolve_candidate(state, architecture, speech.value)
            except _CandidateRejected as error:
                attempts.append(
                    CandidateAttempt(
                        architecture,
                        "rejected",
                        CandidateFailure(architecture, error.reason, error.details),
                    )
                )
                continue
            attempts.append(CandidateAttempt(architecture, "selected"))
            return RuntimeResolution(
                selected,
                self._provenance(policy),
                self._provenance(speech),
                tuple(attempts),
            )
        raise RuntimeResolutionError(
            ResolutionFailureReason.CURRENT_STATE_INVALID,
            {"tenant_id": tenant_id},
            tuple(attempts),
        )

    async def resolve_candidate(
        self, tenant_id: str, architecture: ArchitectureKind
    ) -> ResolvedRuntime:
        state = await self._reader.load(tenant_id)
        speech = self._required_tenant(
            state, tenant_id, "runtime.speech.overrides", SpeechOverrides
        )
        try:
            return self._resolve_candidate(state, architecture, speech.value)
        except _CandidateRejected as error:
            raise RuntimeResolutionError(
                error.reason,
                error.details,
                (
                    CandidateAttempt(
                        architecture,
                        "rejected",
                        CandidateFailure(architecture, error.reason, error.details),
                    ),
                ),
            ) from None

    def _resolve_candidate(
        self,
        state: RuntimeResolutionState,
        architecture: ArchitectureKind,
        speech: SpeechOverrides,
    ) -> ResolvedRuntime:
        if architecture == "cascade":
            return self._cascade(state, speech)
        return self._realtime(state, speech)

    def _cascade(
        self, state: RuntimeResolutionState, speech: SpeechOverrides
    ) -> ResolvedCascadeRuntime:
        llm = self._platform(state, "runtime.llm.defaults", LLMDefaults)
        stt = self._platform(state, "runtime.stt.defaults", STTDefaults)
        tts = self._platform(state, "runtime.tts.defaults", TTSDefaults)
        execution = self._platform(
            state, "runtime.cascade.execution.defaults", CascadeExecutionDefaults
        )
        llm_resource = self._resource(
            state, llm.value.deployment_ref, DeploymentKind.LLM, llm
        )
        stt_resource = self._resource(
            state, stt.value.deployment_ref, DeploymentKind.STT, stt
        )
        tts_resource = self._resource(
            state, tts.value.deployment_ref, DeploymentKind.TTS, tts
        )
        if (
            isinstance(execution.value.stt_commit, ProviderVADCommitPolicy)
            and stt_resource.connection.provider_kind != "elevenlabs"
        ):
            self._reject(
                ResolutionFailureReason.INCOMPATIBLE_PROVIDER,
                component_kind="runtime.cascade.execution.defaults",
                provider_kind=stt_resource.connection.provider_kind,
                requirement="provider_vad",
            )
        voice = speech.voices.cascade or tts.value.default_voice_id
        return ResolvedCascadeRuntime(
            "cascade",
            ResolvedCascadeLLM(self._provenance(llm), llm.value, llm_resource),
            ResolvedCascadeSTT(
                self._provenance(stt),
                stt.value,
                stt_resource,
                speech.language,
                ResolvedSpeechHints(
                    ResolvedKeyterms(
                        SpeechHintStatus.APPLIED, tuple(speech.stt.keyterms)
                    )
                ),
            ),
            ResolvedCascadeTTS(
                self._provenance(tts), tts.value, tts_resource, str(voice)
            ),
            ResolvedCascadeExecution(self._provenance(execution), execution.value),
        )

    def _realtime(
        self, state: RuntimeResolutionState, speech: SpeechOverrides
    ) -> ResolvedRealtimeRuntime:
        policy = self._platform(
            state, "runtime.realtime.execution.defaults", RealtimeExecutionDefaults
        )
        model = self._resource(
            state, policy.value.deployment_ref, DeploymentKind.REALTIME
        )
        transcription = self._resource(
            state,
            policy.value.input_transcription.deployment_ref,
            DeploymentKind.STT,
        )
        capabilities = model.deployment.realtime_capabilities
        if capabilities is None:
            self._reject(
                ResolutionFailureReason.UNSUPPORTED_CAPABILITY,
                deployment_ref=model.deployment.ref.value,
                capability="realtime",
            )
        if isinstance(policy.value.turn_completion, ServerVADTurnCompletion):
            supported = capabilities.supports_server_vad
            capability = "server_vad"
        else:
            supported = capabilities.supports_semantic_vad
            capability = "semantic_vad"
        if not supported:
            self._reject(
                ResolutionFailureReason.UNSUPPORTED_CAPABILITY,
                deployment_ref=model.deployment.ref.value,
                capability=capability,
            )
        transcription_capabilities = transcription.deployment.stt_capabilities
        if (
            transcription_capabilities is None
            or not transcription_capabilities.supports_realtime_input_transcription
        ):
            self._reject(
                ResolutionFailureReason.UNSUPPORTED_CAPABILITY,
                deployment_ref=transcription.deployment.ref.value,
                capability="realtime_input_transcription",
            )
        if (
            model.connection.provider_kind == "azure_openai"
            and model.connection.ref != transcription.connection.ref
        ):
            self._reject(
                ResolutionFailureReason.INCOMPATIBLE_CONNECTION,
                realtime_connection_ref=model.connection.ref.value,
                transcription_connection_ref=transcription.connection.ref.value,
                invariant="azure_same_connection",
            )
        return ResolvedRealtimeRuntime(
            "realtime",
            ResolvedRealtimeModel(self._provenance(policy), model),
            ResolvedRealtimeTranscription(
                transcription,
                speech.language,
                ResolvedSpeechHints(
                    ResolvedKeyterms(
                        SpeechHintStatus.UNSUPPORTED, tuple(speech.stt.keyterms)
                    )
                ),
            ),
            str(speech.voices.realtime or policy.value.default_voice),
            policy.value.turn_completion,
            policy.value.interruption,
        )

    def _resource(
        self,
        state: RuntimeResolutionState,
        deployment_ref: UUID,
        kind: DeploymentKind,
        component: _ActiveRuntimeComponent[Any] | None = None,
    ) -> ResolvedProviderResource:
        deployment = state.deployments.get(deployment_ref)
        if deployment is None:
            self._reject(
                ResolutionFailureReason.MISSING_RESOURCE,
                resource_type="model_deployment",
                resource_id=deployment_ref,
            )
        if not deployment.enabled:
            self._reject(
                ResolutionFailureReason.RESOURCE_DISABLED,
                resource_type="model_deployment",
                resource_id=deployment_ref,
            )
        if deployment.deployment_kind is not kind:
            self._reject(
                ResolutionFailureReason.WRONG_RESOURCE_KIND,
                resource_type="model_deployment",
                resource_id=deployment_ref,
                expected_kind=kind.value,
                actual_kind=deployment.deployment_kind.value,
            )
        connection = state.connections.get(deployment.connection_ref.value)
        if connection is None:
            self._reject(
                ResolutionFailureReason.MISSING_RESOURCE,
                resource_type="provider_connection",
                resource_id=deployment.connection_ref.value,
            )
        if not connection.enabled:
            self._reject(
                ResolutionFailureReason.RESOURCE_DISABLED,
                resource_type="provider_connection",
                resource_id=connection.ref.value,
            )
        credential = state.credentials.get(connection.credential_ref.value)
        if credential is None:
            self._reject(
                ResolutionFailureReason.MISSING_RESOURCE,
                resource_type="credential",
                resource_id=connection.credential_ref.value,
            )
        if credential.status is CredentialStatus.REVOKED:
            self._reject(
                ResolutionFailureReason.CREDENTIAL_REVOKED,
                credential_ref=credential.ref.value,
            )
        if credential.active_version_id is None:
            self._reject(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                credential_ref=credential.ref.value,
                state="missing_active_version",
            )
        try:
            provider = self._providers.resolve(connection.provider_kind)
            provider.validate_connection(connection.connection_config)
            provider.validate_deployment(kind, deployment.deployment_config)
        except InvalidManagedResource as error:
            self._reject(
                ResolutionFailureReason.INCOMPATIBLE_PROVIDER,
                deployment_ref=deployment.ref.value,
                provider_kind=connection.provider_kind,
                validation_error=type(error).__name__,
            )
        if component is not None:
            try:
                definition = self._registry.resolve(component.address)
                assert definition.validate_deployment is not None
                definition.validate_deployment(component.value, deployment)
            except ComponentError as error:
                self._reject(
                    ResolutionFailureReason.UNSUPPORTED_CAPABILITY,
                    deployment_ref=deployment.ref.value,
                    validation_error=type(error).__name__,
                )
        return ResolvedProviderResource(
            deployment,
            connection,
            CredentialProvenance(
                credential.ref.value,
                credential.generation,
                credential.status.value,
                credential.active_version_id,
                credential.active_secret_version_number,
            ),
        )

    def _required_tenant[T](
        self,
        state: RuntimeResolutionState,
        tenant_id: str,
        kind: str,
        expected: type[T],
    ) -> _ActiveRuntimeComponent[T]:
        address = ComponentAddress(ComponentKind(kind), TenantScope(tenant_id))
        stored = state.components.get(address)
        if stored is None:
            raise RuntimeResolutionError(
                ResolutionFailureReason.MISSING_TENANT_COMPONENT,
                {"tenant_id": tenant_id, "component_kind": kind},
            )
        return self._typed(stored, expected)

    def _platform[T](
        self,
        state: RuntimeResolutionState,
        kind: str,
        expected: type[T],
    ) -> _ActiveRuntimeComponent[T]:
        address = ComponentAddress(ComponentKind(kind), PlatformScope())
        stored = state.components.get(address)
        if stored is None:
            self._reject(
                ResolutionFailureReason.MISSING_PLATFORM_COMPONENT,
                component_kind=kind,
            )
        try:
            return self._typed(stored, expected)
        except RuntimeResolutionError as error:
            raise _CandidateRejected(error.reason, error.details) from None

    def _typed[T](
        self, stored: StoredActiveRuntimeComponent, expected: type[T]
    ) -> _ActiveRuntimeComponent[T]:
        try:
            definition = self._registry.resolve(stored.address)
            if stored.schema_version != definition.current_schema_version:
                raise ValueError("unsupported active schema version")
            value = definition.deserialize(stored.value)
        except (ComponentError, ValueError) as error:
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {
                    "component_kind": str(stored.address.kind),
                    "validation_error": type(error).__name__,
                },
            ) from None
        if not isinstance(value, expected):
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {"component_kind": str(stored.address.kind)},
            )
        return _ActiveRuntimeComponent(
            stored.address,
            stored.revision_id,
            stored.revision_number,
            stored.schema_version,
            cast(T, value),
        )

    @staticmethod
    def _provenance(revision: _ActiveRuntimeComponent[Any]) -> ComponentProvenance:
        return ComponentProvenance(
            str(revision.address.kind),
            revision.address.scope.type.value,
            revision.address.scope.key,
            revision.revision_id,
            revision.revision_number,
            revision.schema_version,
        )

    @staticmethod
    def _reject(reason: ResolutionFailureReason, **details: object) -> NoReturn:
        raise _CandidateRejected(reason, details)
