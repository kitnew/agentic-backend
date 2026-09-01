from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from control_plane.application.runtime_resolver import (
    RuntimeResolutionState,
    RuntimeResolver,
    StoredActiveRuntimeComponent,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.domain.providers import default_provider_registry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.domain.runtime_execution_snapshot import (
    content_hash,
    snapshot_from_payload,
    snapshot_payload,
)
from control_plane.domain.runtime_resolution import (
    ResolutionFailureReason,
    ResolvedCascadeRuntime,
    ResolvedRealtimeRuntime,
    RuntimeResolutionError,
    SpeechHintStatus,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient

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


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def component(
    kind: str, value: dict[str, object], tenant: bool = False, number: int = 1
):
    address = ComponentAddress(
        ComponentKind(kind), TenantScope(TENANT) if tenant else PlatformScope()
    )
    return address, StoredActiveRuntimeComponent(
        address, UUID(int=100 + len(kind)), number, 1, value
    )


def credential(name: str) -> Credential:
    ref = IDS[f"{name}_credential"]
    return Credential(
        CredentialRef(ref),
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
        llm,
        realtime,
        stt,
        True,
        5,
        NOW,
        "test",
        NOW,
        "test",
    )


def state(architectures: list[str] | None = None) -> RuntimeResolutionState:
    architectures = architectures or ["realtime", "cascade"]
    values = [
        component(
            "runtime.architecture.policy", {"architectures": architectures}, True
        ),
        component(
            "runtime.speech.overrides",
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": None},
            },
            True,
        ),
        component(
            "runtime.llm.defaults",
            {
                "deployment_ref": str(IDS["llm"]),
                "reasoning_effort": "high",
                "max_completion_tokens": 1024,
            },
        ),
        component("runtime.stt.defaults", {"deployment_ref": str(IDS["cascade_stt"])}),
        component(
            "runtime.tts.defaults",
            {
                "deployment_ref": str(IDS["tts"]),
                "default_voice_id": "platform-cascade",
                "min_sentence_chars": 20,
            },
        ),
        component(
            "runtime.cascade.execution.defaults",
            {
                "speech_activity": {
                    "min_speech_seconds": 0.05,
                    "min_silence_seconds": 0.25,
                    "activation_threshold": 0.5,
                },
                "stt_commit": {"strategy": "local_vad"},
                "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.7},
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
            },
        ),
        component(
            "runtime.realtime.execution.defaults",
            {
                "deployment_ref": str(IDS["realtime"]),
                "input_transcription": {"deployment_ref": str(IDS["realtime_stt"])},
                "default_voice": "platform-realtime",
                "turn_completion": {"strategy": "server_vad"},
                "interruption": {"enabled": True},
            },
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
    return RuntimeResolutionState(dict(values), deployments, connections, credentials)


def resolver(value: RuntimeResolutionState) -> RuntimeResolver:
    registry = ComponentRegistry()
    register_runtime_components(registry)
    return RuntimeResolver(registry, default_provider_registry(), Reader(value))


def without_component(
    value: RuntimeResolutionState, kind: str
) -> RuntimeResolutionState:
    components = {
        address: component
        for address, component in value.components.items()
        if str(address.kind) != kind
    }
    return replace(value, components=components)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "runtime.architecture.policy",
        "runtime.speech.overrides",
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
async def test_exact_policy_order_is_authoritative(
    architectures: list[str], expected: str
) -> None:
    result = await resolver(state(architectures)).resolve_runtime(TENANT)

    assert result.selected.architecture == expected
    assert [attempt.architecture for attempt in result.attempts] == [expected]


@pytest.mark.asyncio
async def test_realtime_failure_falls_back_with_ordered_diagnostics() -> None:
    value = state()
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(deployments[IDS["realtime"]], enabled=False)

    result = await resolver(replace(value, deployments=deployments)).resolve_runtime(
        TENANT
    )

    assert result.selected.architecture == "cascade"
    assert [attempt.architecture for attempt in result.attempts] == [
        "realtime",
        "cascade",
    ]
    assert result.attempts[0].failure is not None
    assert (
        result.attempts[0].failure.reason is ResolutionFailureReason.RESOURCE_DISABLED
    )


@pytest.mark.asyncio
async def test_absent_architecture_is_never_a_fallback() -> None:
    value = state(["realtime"])
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(deployments[IDS["realtime"]], enabled=False)

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(replace(value, deployments=deployments)).resolve_runtime(TENANT)

    assert [attempt.architecture for attempt in captured.value.attempts] == ["realtime"]


@pytest.mark.asyncio
async def test_execution_snapshot_payload_round_trips_and_is_secret_free() -> None:
    resolution = await resolver(state(["cascade"])).resolve_runtime(TENANT)
    payload = snapshot_payload(TENANT, resolution)
    restored = snapshot_from_payload(UUID(int=999), NOW, payload, content_hash(payload))

    assert restored.runtime == resolution.selected
    assert restored.resolution == resolution
    assert all(field not in str(payload).lower() for field in ("ciphertext", "nonce", "key_id", "secret_envelope"))
    assert content_hash(payload) == content_hash(snapshot_payload(TENANT, resolution))


@pytest.mark.asyncio
async def test_cascade_materializes_current_state_hints_voice_and_provenance() -> None:
    result = await resolver(state(["cascade"])).resolve_runtime(TENANT)
    selected = result.selected

    assert isinstance(selected, ResolvedCascadeRuntime)
    assert selected.stt.language == "sk"
    assert selected.stt.speech_hints.keyterms.status is SpeechHintStatus.APPLIED
    assert selected.stt.speech_hints.keyterms.values == ("Penzión Grand",)
    assert selected.tts.voice == "platform-cascade"
    assert selected.llm.resource.deployment.generation == 5
    assert selected.llm.resource.connection.generation == 4
    assert selected.llm.resource.credential.generation == 3
    assert selected.llm.component.revision_number == 1
    assert result.architecture_policy.component_kind == "runtime.architecture.policy"


@pytest.mark.asyncio
async def test_tenant_voices_override_platform_defaults() -> None:
    value = state()
    components = dict(value.components)
    address = ComponentAddress(
        ComponentKind("runtime.speech.overrides"), TenantScope(TENANT)
    )
    speech = components[address]
    components[address] = replace(
        speech,
        value={
            **speech.value,
            "voices": {"cascade": "tenant-cascade", "realtime": "tenant-realtime"},
        },
    )

    realtime = await resolver(replace(value, components=components)).resolve_runtime(
        TENANT
    )
    cascade = await resolver(replace(value, components=components)).resolve_candidate(
        TENANT, "cascade"
    )

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
            stt_capabilities=STTCapabilities(False, False),
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
    components = dict(value.components)
    address = ComponentAddress(
        ComponentKind("runtime.cascade.execution.defaults"), PlatformScope()
    )
    execution = components[address]
    components[address] = replace(
        execution,
        value={
            **execution.value,
            "stt_commit": {
                "strategy": "provider_vad",
                "provider_vad": {
                    "threshold": 0.5,
                    "silence_threshold_seconds": 0.35,
                    "min_speech_ms": 100,
                    "min_silence_ms": 350,
                },
            },
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
                components=components,
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
    assert selected.input_transcription.language == "sk"
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
            realtime_capabilities=RealtimeCapabilities(False, True),
        )
    elif mutation == "transcription_capability":
        deployments[IDS["realtime_stt"]] = replace(
            deployments[IDS["realtime_stt"]],
            stt_capabilities=STTCapabilities(False, False),
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
    components = dict(value.components)
    address = ComponentAddress(
        ComponentKind("runtime.realtime.execution.defaults"), PlatformScope()
    )
    policy = components[address]
    components[address] = replace(
        policy,
        value={
            **policy.value,
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "auto"},
        },
    )
    deployments = dict(value.deployments)
    deployments[IDS["realtime"]] = replace(
        deployments[IDS["realtime"]],
        realtime_capabilities=RealtimeCapabilities(True, False),
    )

    with pytest.raises(RuntimeResolutionError) as captured:
        await resolver(
            replace(value, components=components, deployments=deployments)
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


@pytest.mark.asyncio
async def test_http_returns_typed_resolution_without_plaintext() -> None:
    app = create_http_app(
        Lifecycle(),  # type: ignore[arg-type]
        runtime_resolver=resolver(state()),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/runtime/resolve/tenant/{TENANT}")

    assert response.status_code == 200
    assert response.json()["selected"]["architecture"] == "realtime"
    assert response.json()["attempts"] == [
        {"architecture": "realtime", "status": "selected", "failure": None}
    ]
    assert "plaintext-api-key" not in response.text


@pytest.mark.asyncio
async def test_http_returns_structured_unresolvable_response() -> None:
    app = create_http_app(
        Lifecycle(),  # type: ignore[arg-type]
        runtime_resolver=resolver(
            without_component(state(), "runtime.architecture.policy")
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/runtime/resolve/tenant/{TENANT}")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "runtime_resolution_failed",
        "reason": "MISSING_TENANT_COMPONENT",
        "details": {
            "tenant_id": TENANT,
            "component_kind": "runtime.architecture.policy",
        },
        "attempts": [],
    }
