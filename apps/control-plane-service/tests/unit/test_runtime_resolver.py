from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.runtime_resolver import (
    RuntimeResolutionState,
    RuntimeResolver,
    StoredActiveRuntimeComponent,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    PlatformScope,
    ProfileScope,
    SystemScope,
    TenantScope,
)
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.live_components import LiveComponentState
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
    TTSCapabilities,
)
from control_plane.domain.registries import ProviderKindRegistry
from control_plane.domain.runtime_execution_snapshot import (
    content_hash,
    snapshot_payload,
)
from control_plane.domain.runtime_resolution import (
    ComponentProvenance,
    ResolutionFailureReason,
    ResolvedCascadeRuntime,
    ResolvedRealtimeRuntime,
    RuntimeResolutionError,
    SpeechHintStatus,
)

TENANT = "tenant-a"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
IDS = {
    name: UUID(int=index)
    for index, name in enumerate(
        (
            "cascade_credential",
            "realtime_credential",
            "eleven_credential",
            "cascade_connection",
            "realtime_connection",
            "eleven_connection",
            "llm",
            "realtime",
            "realtime_stt",
            "cascade_stt",
            "tts",
        ),
        1,
    )
}


class Reader:
    def __init__(self, state: RuntimeResolutionState) -> None:
        self.state = state

    async def load(self, _tenant_id: str) -> RuntimeResolutionState:
        return self.state


def component(
    kind: str, value: dict[str, object], tenant: bool = False, number: int = 1
):
    address = ComponentAddress(
        ComponentKind(kind), TenantScope(TENANT) if tenant else PlatformScope()
    )
    return address, StoredActiveRuntimeComponent(
        address, UUID(int=100 + len(kind)), number, 1, value
    )


def live_component(
    kind: str, value: dict[str, object], generation: int = 1, *, tenant: bool = False
):
    address = ComponentAddress(
        ComponentKind(kind), TenantScope(TENANT) if tenant else SystemScope()
    )
    return address, LiveComponentState(address, value, 1, generation, NOW, "test")


def credential(name: str) -> Credential:
    ref = IDS[f"{name}_credential"]
    return Credential(
        CredentialRef(ref),
        PlatformCredentialScope(),
        name,
        UUID(int=500 + ref.int),
        1,
        CredentialStatus.ACTIVE,
        3,
        NOW,
        "test",
        None,
        None,
    )


def connection(name: str, provider: str, credential_name: str) -> ProviderConnection:
    ref = IDS[f"{name}_connection"]
    config = (
        {"endpoint": f"https://{name}.openai.azure.com"}
        if provider == "azure_openai"
        else {}
    )
    return ProviderConnection(
        ProviderConnectionRef(ref),
        name,
        provider,
        CredentialRef(IDS[f"{credential_name}_credential"]),
        config,
        True,
        4,
        NOW,
        "test",
        NOW,
        "test",
    )


def deployment(
    name: str,
    kind: DeploymentKind,
    connection_name: str,
    *,
    llm: LLMCapabilities | None = None,
    realtime: RealtimeCapabilities | None = None,
    stt: STTCapabilities | None = None,
) -> ModelDeployment:
    provider = "azure_openai" if connection_name != "eleven" else "elevenlabs"
    config = (
        {"deployment_name": name, "model": name, "api_version": "2026-01-01"}
        if kind is DeploymentKind.LLM
        else {"deployment_name": name}
        if provider == "azure_openai"
        else {"model_id": name}
    )
    return ModelDeployment(
        ModelDeploymentRef(IDS[name]),
        name,
        ProviderConnectionRef(IDS[f"{connection_name}_connection"]),
        kind,
        config,
        llm or realtime or stt or TTSCapabilities(),
        True,
        5,
        NOW,
        "test",
        NOW,
        "test",
    )


def state(architectures: list[str] | None = None) -> RuntimeResolutionState:
    architectures = architectures or ["realtime"]
    components = [
        component(
            "BusinessInfo",
            {
                "business": {"name": "Grand", "type": "hotel"},
                "contact": {"phones": [], "emails": []},
                "localization": {
                    "default_locale": "sk-SK",
                    "timezone": "Europe/Bratislava",
                },
            },
            True,
        ),
    ]
    live_components = [
        live_component(
            "LLMDefaults",
            {
                "deployment_ref": str(IDS["llm"]),
                "reasoning_effort": "high",
                "max_completion_tokens": 1024,
            },
        ),
        live_component("STTDefaults", {"deployment_ref": str(IDS["cascade_stt"])}),
        live_component(
            "TTSDefaults",
            {
                "deployment_ref": str(IDS["tts"]),
                "default_voice_id": "platform-cascade",
            },
        ),
        live_component(
            "Policies",
            {
                "cascade": {
                    "speech_activity": {
                        "min_speech_seconds": 0.05,
                        "min_silence_seconds": 0.25,
                        "activation_threshold": 0.5,
                    },
                    "stt_commit": {"strategy": "local_vad"},
                    "endpointing": {
                        "min_delay_seconds": 0.1,
                        "max_delay_seconds": 0.7,
                    },
                    "interruption": {
                        "enabled": True,
                        "min_duration_seconds": 0.5,
                        "min_words": 0,
                        "false_interruption_timeout_seconds": 2.0,
                        "resume_after_false_interruption": True,
                    },
                    "response_scheduling": {
                        "preemptive_generation": True,
                        "preemptive_tts": True,
                    },
                    "tokenizer": {"min_sentence_chars": 20},
                }
            },
        ),
        live_component(
            "RealtimeDefaults",
            {
                "deployment_ref": str(IDS["realtime"]),
                "input_transcription": {"deployment_ref": str(IDS["realtime_stt"])},
                "default_voice": "platform-realtime",
                "turn_completion": {"strategy": "server_vad"},
                "interruption": {"enabled": True},
            },
        ),
        live_component(
            "Architecture", {"architecture_key": architectures[0]}, tenant=True
        ),
        live_component(
            "RuntimeOverrides",
            {"stt": {"keyterms": ["Penzión Grand"]}},
            tenant=True,
        ),
    ]
    credentials = {
        value.ref.value: value
        for value in (
            credential("cascade"),
            credential("realtime"),
            credential("eleven"),
        )
    }
    connections = {
        value.ref.value: value
        for value in (
            connection("cascade", "azure_openai", "cascade"),
            connection("realtime", "azure_openai", "realtime"),
            connection("eleven", "elevenlabs", "eleven"),
        )
    }
    deployments = {
        value.ref.value: value
        for value in (
            deployment(
                "llm", DeploymentKind.LLM, "cascade", llm=LLMCapabilities(True, True)
            ),
            deployment(
                "realtime",
                DeploymentKind.REALTIME,
                "realtime",
                realtime=RealtimeCapabilities(True, True),
            ),
            deployment(
                "realtime_stt",
                DeploymentKind.STT,
                "realtime",
                stt=STTCapabilities(False, True),
            ),
            deployment(
                "cascade_stt",
                DeploymentKind.STT,
                "eleven",
                stt=STTCapabilities(True, False),
            ),
            deployment("tts", DeploymentKind.TTS, "eleven"),
        )
    }
    return RuntimeResolutionState(
        dict(components),
        dict(live_components),
        deployments,
        connections,
        credentials,
    )


def resolver(value: RuntimeResolutionState) -> RuntimeResolver:
    registry = default_component_definition_registry()
    return RuntimeResolver(registry, ProviderKindRegistry(), Reader(value))


def execution_resolver(
    value: RuntimeResolutionState,
) -> tuple[ExecutionResolver, RuntimeResolutionState]:
    registry = default_component_definition_registry()
    components = dict(value.components)
    for address, raw in (
        (
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            {"content": "system"},
        ),
        (
            ComponentAddress(ComponentKind("ProfilePrompt"), ProfileScope("default")),
            {"content": "profile"},
        ),
        (
            ComponentAddress(ComponentKind("TenantPrompt"), TenantScope(TENANT)),
            {"content": "tenant"},
        ),
        (
            ComponentAddress(ComponentKind("Knowledge"), TenantScope(TENANT)),
            {"content": "knowledge"},
        ),
        (
            ComponentAddress(ComponentKind("AgentPersonality"), TenantScope(TENANT)),
            {
                "identity": "default",
                "display_name": "Amélia",
                "greeting": "Dobrý deň 🌿",
                "conversation_scope": "property_only",
            },
        ),
        (
            ComponentAddress(ComponentKind("ActionsDefinition"), TenantScope(TENANT)),
            {"actions": {}},
        ),
    ):
        components[address] = StoredActiveRuntimeComponent(
            address, UUID(int=900 + len(components)), 2, 1, raw
        )
    live_components = dict(value.live_components)
    for kind, raw in (
        ("ProfileReference", {"profile_key": "default"}),
        ("ActionsAvailability", {"actions": {}}),
    ):
        address, stored = live_component(kind, raw, tenant=True)
        live_components[address] = stored
    enriched = replace(value, components=components, live_components=live_components)
    return ExecutionResolver(
        registry,
        RuntimeResolver(registry, ProviderKindRegistry(), Reader(enriched)),
    ), enriched


def without_component(
    value: RuntimeResolutionState, kind: str
) -> RuntimeResolutionState:
    components = {
        address: component
        for address, component in value.components.items()
        if str(address.kind) != kind
    }
    live_components = {
        address: component
        for address, component in value.live_components.items()
        if str(address.kind) != kind
    }
    return replace(value, components=components, live_components=live_components)


def without_live_component(
    value: RuntimeResolutionState, kind: str
) -> RuntimeResolutionState:
    live_components = {
        address: component
        for address, component in value.live_components.items()
        if str(address.kind) != kind
    }
    return replace(value, live_components=live_components)


@pytest.mark.asyncio
async def test_complete_system_live_state_is_required_without_legacy_fallback() -> None:
    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(without_live_component(state(), "LLMDefaults")).resolve_runtime(
            TENANT
        )

    assert captured.value.reason is ResolutionFailureReason.MISSING_PLATFORM_COMPONENT
    assert captured.value.details["component_kind"] == "LLMDefaults"
    assert captured.value.attempts == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "Architecture",
        "RuntimeOverrides",
        "BusinessInfo",
    ],
)
async def test_tenant_components_are_required(kind: str) -> None:
    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(without_component(state(), kind)).resolve_runtime(TENANT)

    assert captured.value.reason is ResolutionFailureReason.MISSING_TENANT_COMPONENT
    assert captured.value.details["component_kind"] == kind
    assert captured.value.attempts == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "architectures, expected",
    [
        (["cascade"], "cascade"),
        (["realtime"], "realtime"),
        (["realtime", "cascade"], "realtime"),
    ],
)
async def test_exact_architecture_selection_is_authoritative(
    architectures: list[str], expected: str
) -> None:
    result = await resolver(state(architectures)).resolve_runtime(TENANT)

    assert result.selected.architecture == expected
    assert [attempt.architecture for attempt in result.attempts] == [expected]


@pytest.mark.asyncio
async def test_realtime_failure_does_not_fall_back() -> None:
    value = state()
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(deployments[IDS["realtime"]], enabled=False)

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(replace(value, deployments=deployments)).resolve_runtime(TENANT)

    assert [attempt.architecture for attempt in captured.value.attempts] == ["realtime"]
    assert captured.value.attempts[0].failure is not None
    assert (
        captured.value.attempts[0].failure.reason
        is ResolutionFailureReason.RESOURCE_DISABLED
    )


@pytest.mark.asyncio
async def test_absent_architecture_is_never_a_fallback() -> None:
    value = state(["realtime"])
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(deployments[IDS["realtime"]], enabled=False)

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(replace(value, deployments=deployments)).resolve_runtime(TENANT)

    assert [attempt.architecture for attempt in captured.value.attempts] == ["realtime"]


def test_execution_snapshot_payload_is_target_only_and_secret_free() -> None:
    target = {
        "backend": {"architecture": "cascade"},
        "voice": {"architecture": "cascade"},
        "actions": {},
        "bindings": {"runtime_secrets": {}, "integrations": {}, "handoff": {}},
    }
    payload = snapshot_payload(target)

    assert set(payload) == {"backend", "voice", "actions", "bindings"}
    assert not set(payload) & {"execution", "agent", "runtime", "resolution"}
    assert all(
        field not in str(payload).lower()
        for field in ("ciphertext", "nonce", "key_id", "secret_envelope")
    )
    assert content_hash(payload) == content_hash(snapshot_payload(target))


def test_execution_resolution_contains_tenant_agent_context_and_provenance() -> None:
    value = state(["cascade"])
    resolver, enriched = execution_resolver(value)
    execution = resolver.resolve_state(TENANT, enriched)

    assert execution.agent.display_name == "Amélia"
    assert execution.agent.agent_profile == "default"
    assert execution.agent.greeting == "Dobrý deň 🌿"
    assert execution.agent.conversation_scope == "property_only"
    assert execution.agent.locale == "sk-SK"
    assert execution.agent.timezone == "Europe/Bratislava"
    agent_provenance = execution.provenance["agent"]
    selection_provenance = execution.provenance["profile_selection"]
    assert isinstance(agent_provenance, ComponentProvenance)
    assert isinstance(selection_provenance, ComponentProvenance)
    assert agent_provenance.component_kind == "AgentPersonality"
    assert selection_provenance.component_kind == "ProfileReference"


def test_execution_resolution_requires_agent_component() -> None:
    value = state(["cascade"])
    resolver, enriched = execution_resolver(value)
    without_agent = without_component(enriched, "AgentPersonality")

    with pytest.raises(RuntimeResolutionError) as captured:
        resolver.resolve_state(TENANT, without_agent)

    assert captured.value.reason is ResolutionFailureReason.MISSING_TENANT_COMPONENT
    assert captured.value.details["component_kind"] == "AgentPersonality"


def test_execution_snapshot_target_hashes_context_changes() -> None:
    value = state(["cascade"])
    resolver, enriched = execution_resolver(value)
    execution = resolver.resolve_state(TENANT, enriched)
    target = {
        "backend": {},
        "voice": {"agent": execution.agent},
        "actions": {},
        "bindings": {},
    }
    payload = snapshot_payload(target)
    changed = {
        **target,
        "voice": {"agent": replace(execution.agent, greeting="Nový deň 🌿")},
    }
    assert content_hash(payload) != content_hash(
        snapshot_payload(changed)
    )


def test_execution_snapshot_contains_no_credential_secret_version_internals() -> None:
    resolver, enriched = execution_resolver(state(["cascade"]))
    execution = resolver.resolve_state(TENANT, enriched)
    payload = snapshot_payload({"voice": {"runtime": execution.runtime.selected}})

    serialized = str(payload).lower()
    assert "active_version_id" not in serialized
    assert "active_secret_version_number" not in serialized


def test_target_execution_state_does_not_embed_component_provenance() -> None:
    resolver, enriched = execution_resolver(state(["cascade"]))
    execution = resolver.resolve_state(TENANT, enriched)
    assert "provenance" not in str(execution.actions).lower()
    assert all(
        set(action)
        == {
            "key",
            "phase",
            "definition",
            "execution_plan",
            "integration",
        }
        for action in execution.actions
    )


@pytest.mark.asyncio
async def test_cascade_materializes_current_state_hints_voice_and_provenance() -> None:
    result = await resolver(state(["cascade"])).resolve_runtime(TENANT)
    selected = result.selected

    assert isinstance(selected, ResolvedCascadeRuntime)
    assert selected.stt.language == "sk-SK"
    assert selected.stt.speech_hints.keyterms.status is SpeechHintStatus.APPLIED
    assert selected.stt.speech_hints.keyterms.values == ("Penzión Grand",)
    assert selected.tts.voice == "platform-cascade"
    assert selected.llm.resource.deployment.generation == 5
    assert selected.llm.resource.connection.generation == 4
    assert selected.llm.resource.credential.generation == 3
    assert selected.llm.component.revision_number is None
    assert selected.llm.component.component_kind == "LLMDefaults"
    assert result.architecture_policy.component_kind == "Architecture"


@pytest.mark.asyncio
async def test_tenant_voices_override_platform_defaults() -> None:
    value = state()
    live_components = dict(value.live_components)
    address = ComponentAddress(ComponentKind("RuntimeOverrides"), TenantScope(TENANT))
    overrides = live_components[address]
    live_components[address] = replace(
        overrides,
        value={
            **overrides.value,
            "tts": {"voice_id": "tenant-cascade"},
            "realtime": {"voice": "tenant-realtime"},
        },
    )

    updated = replace(value, live_components=live_components)
    realtime = await resolver(updated).resolve_runtime(TENANT)
    cascade = await resolver(updated).resolve_candidate(TENANT, "cascade")

    assert isinstance(realtime.selected, ResolvedRealtimeRuntime)
    assert realtime.selected.voice == "tenant-realtime"
    assert isinstance(cascade, ResolvedCascadeRuntime)
    assert cascade.tts.voice == "tenant-cascade"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("deployment_disabled", ResolutionFailureReason.RESOURCE_DISABLED),
        ("connection_disabled", ResolutionFailureReason.RESOURCE_DISABLED),
        ("credential_revoked", ResolutionFailureReason.CREDENTIAL_REVOKED),
        ("capability_changed", ResolutionFailureReason.UNSUPPORTED_CAPABILITY),
    ],
)
async def test_cascade_revalidates_live_resources(mutation: str, reason) -> None:
    value = state(["cascade"])
    deployments = dict(value.deployments)
    connections = dict(value.connections)
    credentials = dict(value.credentials)
    if mutation == "deployment_disabled":
        deployments[IDS["cascade_stt"]] = replace(
            deployments[IDS["cascade_stt"]], enabled=False
        )
    elif mutation == "connection_disabled":
        connections[IDS["eleven_connection"]] = replace(
            connections[IDS["eleven_connection"]], enabled=False
        )
    elif mutation == "credential_revoked":
        credentials[IDS["eleven_credential"]] = replace(
            credentials[IDS["eleven_credential"]],
            status=CredentialStatus.REVOKED,
            active_version_id=None,
        )
    else:
        deployments[IDS["cascade_stt"]] = replace(
            deployments[IDS["cascade_stt"]],
            capabilities=STTCapabilities(False, False),
        )

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(
            replace(
                value,
                deployments=deployments,
                connections=connections,
                credentials=credentials,
            )
        ).resolve_runtime(TENANT)

    assert captured.value.attempts[0].failure is not None
    assert captured.value.attempts[0].failure.reason is reason


@pytest.mark.asyncio
async def test_provider_vad_is_revalidated() -> None:
    value = state(["cascade"])
    live_components = dict(value.live_components)
    address = ComponentAddress(ComponentKind("Policies"), SystemScope())
    policies = live_components[address]
    cascade = dict(policies.value["cascade"])
    live_components[address] = replace(
        policies,
        value={
            "cascade": {
                **cascade,
                "stt_commit": {
                    "strategy": "provider_vad",
                    "provider_vad": {
                        "threshold": 0.5,
                        "silence_threshold_seconds": 0.35,
                        "min_speech_ms": 100,
                        "min_silence_ms": 350,
                    },
                },
            }
        },
    )
    connections = dict(value.connections)
    connections[IDS["eleven_connection"]] = replace(
        connections[IDS["eleven_connection"]],
        provider_kind="azure_openai",
        connection_config={"endpoint": "https://example.openai.azure.com"},
    )
    deployments = dict(value.deployments)
    deployments[IDS["cascade_stt"]] = replace(
        deployments[IDS["cascade_stt"]],
        deployment_config={"deployment_name": "cascade-stt"},
    )

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(
            replace(
                value,
                live_components=live_components,
                connections=connections,
                deployments=deployments,
            )
        ).resolve_runtime(TENANT)

    assert captured.value.attempts[0].failure is not None
    assert (
        captured.value.attempts[0].failure.reason
        is ResolutionFailureReason.INCOMPATIBLE_PROVIDER
    )


@pytest.mark.asyncio
async def test_realtime_hints_remain_visible_but_do_not_force_fallback() -> None:
    result = await resolver(state()).resolve_runtime(TENANT)
    selected = result.selected

    assert isinstance(selected, ResolvedRealtimeRuntime)
    assert selected.input_transcription.language == "sk-SK"
    assert (
        selected.input_transcription.speech_hints.keyterms.status
        is SpeechHintStatus.UNSUPPORTED
    )
    assert selected.input_transcription.speech_hints.keyterms.values == (
        "Penzión Grand",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("same_connection", ResolutionFailureReason.INCOMPATIBLE_CONNECTION),
        ("vad_capability", ResolutionFailureReason.UNSUPPORTED_CAPABILITY),
        ("transcription_capability", ResolutionFailureReason.UNSUPPORTED_CAPABILITY),
        ("connection_disabled", ResolutionFailureReason.RESOURCE_DISABLED),
        ("credential_revoked", ResolutionFailureReason.CREDENTIAL_REVOKED),
    ],
)
async def test_realtime_revalidates_live_compatibility(mutation: str, reason) -> None:
    value = state(["realtime"])
    deployments = dict(value.deployments)
    credentials = dict(value.credentials)
    if mutation == "same_connection":
        deployments[IDS["realtime_stt"]] = replace(
            deployments[IDS["realtime_stt"]],
            connection_ref=ProviderConnectionRef(IDS["cascade_connection"]),
        )
    elif mutation == "vad_capability":
        deployments[IDS["realtime"]] = replace(
            deployments[IDS["realtime"]],
            capabilities=RealtimeCapabilities(False, True),
        )
    elif mutation == "transcription_capability":
        deployments[IDS["realtime_stt"]] = replace(
            deployments[IDS["realtime_stt"]],
            capabilities=STTCapabilities(False, False),
        )
    elif mutation == "connection_disabled":
        connections = dict(value.connections)
        connections[IDS["realtime_connection"]] = replace(
            connections[IDS["realtime_connection"]], enabled=False
        )
        value = replace(value, connections=connections)
    else:
        credentials[IDS["realtime_credential"]] = replace(
            credentials[IDS["realtime_credential"]],
            status=CredentialStatus.REVOKED,
            active_version_id=None,
        )

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(
            replace(value, deployments=deployments, credentials=credentials)
        ).resolve_runtime(TENANT)

    assert captured.value.attempts[0].failure is not None
    assert captured.value.attempts[0].failure.reason is reason


@pytest.mark.asyncio
async def test_realtime_semantic_vad_capability_is_revalidated() -> None:
    value = state(["realtime"])
    live_components = dict(value.live_components)
    address = ComponentAddress(ComponentKind("RealtimeDefaults"), SystemScope())
    policy = live_components[address]
    live_components[address] = replace(
        policy,
        value={
            **policy.value,
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "auto"},
        },
    )
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(
        deployments[IDS["realtime"]],
        capabilities=RealtimeCapabilities(True, False),
    )

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(
            replace(value, live_components=live_components, deployments=deployments)
        ).resolve_runtime(TENANT)

    assert captured.value.attempts[0].failure is not None
    assert (
        captured.value.attempts[0].failure.reason
        is ResolutionFailureReason.UNSUPPORTED_CAPABILITY
    )


@pytest.mark.asyncio
async def test_repeated_resolution_is_deterministic_and_contains_no_secret() -> None:
    service = resolver(state())

    first = await service.resolve_runtime(TENANT)
    second = await service.resolve_runtime(TENANT)

    assert first == second
    assert "plaintext-api-key" not in repr(first)
