from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from control_plane.application.command_support import IdempotencyKeyReused, StoredReplay
from control_plane.application.system_configuration import (
    SystemConfigurationDesired,
    SystemConfigurationError,
    SystemConfigurationPreconditionFailed,
    SystemConfigurationService,
)
from control_plane.domain.frozen_components import default_component_definition_registry
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

NOW = datetime.now(UTC)


def desired(refs, *, voice="marin"):
    return SystemConfigurationDesired.model_validate(
        {
            "stt_defaults": {"deployment_ref": str(refs["stt"])},
            "llm_defaults": {
                "deployment_ref": str(refs["llm"]),
                "temperature": 0.5,
                "reasoning_effort": "medium",
                "max_completion_tokens": 100,
            },
            "tts_defaults": {
                "deployment_ref": str(refs["tts"]),
                "default_voice_id": voice,
            },
            "realtime_defaults": {
                "deployment_ref": str(refs["realtime"]),
                "input_transcription": {"deployment_ref": str(refs["stt"])},
                "default_voice": "marin",
                "turn_completion": {"strategy": "semantic_vad"},
                "interruption": {"enabled": True},
            },
            "policies": {
                "cascade": {
                    "speech_activity": {
                        "min_speech_seconds": 0.1,
                        "min_silence_seconds": 0.2,
                        "activation_threshold": 0.5,
                    },
                    "stt_commit": {"strategy": "local_vad"},
                    "endpointing": {
                        "min_delay_seconds": 0.1,
                        "max_delay_seconds": 0.2,
                    },
                    "interruption": {
                        "enabled": True,
                        "min_duration_seconds": 0,
                        "min_words": 0,
                        "false_interruption_timeout_seconds": 0,
                        "resume_after_false_interruption": True,
                    },
                    "response_scheduling": {
                        "preemptive_generation": False,
                        "preemptive_tts": False,
                    },
                    "tokenizer": {"min_sentence_chars": 3},
                }
            },
        }
    )


class Repository:
    def __init__(self, resources):
        self.live = {}
        self.resources = resources
        self.set_calls = 0

    async def get(self, address, *, lock=False):
        return self.live.get(address)

    async def set(self, address, value, schema_version, actor):
        self.set_calls += 1
        current = self.live.get(address)
        state_type = __import__(
            "control_plane.domain.live_components", fromlist=["LiveComponentState"]
        ).LiveComponentState
        value = state_type(
            address,
            value,
            schema_version,
            current.generation + 1 if current else 1,
            NOW,
            actor,
        )
        self.live[address] = value
        return value

    async def get_deployment(self, ref, *, lock=False):
        return self.resources[ref]

    async def get_connection(self, ref, *, lock=False):
        return self.resources[ref]

    async def get_credential(self, ref, *, lock=False):
        return self.resources[ref]


class Replays:
    def __init__(self):
        self.values = {}

    async def get(self, principal, operation, key):
        return self.values.get((principal, operation, key))

    async def add(self, principal, operation, key, fingerprint, result):
        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


def setup():
    credential = Credential(
        CredentialRef(uuid4()),
        PlatformCredentialScope(),
        "provider",
        uuid4(),
        1,
        CredentialStatus.ACTIVE,
        1,
        NOW,
        "alice",
        None,
        None,
    )
    connection = ProviderConnection(
        ProviderConnectionRef(uuid4()),
        "provider",
        "azure_openai",
        credential.ref,
        {},
        True,
        1,
        NOW,
        "alice",
        NOW,
        "alice",
    )
    specs = {
        "stt": (DeploymentKind.STT, STTCapabilities(True, True)),
        "llm": (DeploymentKind.LLM, LLMCapabilities(True, True)),
        "tts": (DeploymentKind.TTS, TTSCapabilities()),
        "realtime": (DeploymentKind.REALTIME, RealtimeCapabilities(True, True)),
    }
    deployments = {
        key: ModelDeployment(
            ModelDeploymentRef(uuid4()),
            key,
            connection.ref,
            kind,
            {},
            capabilities,
            True,
            1,
            NOW,
            "alice",
            NOW,
            "alice",
        )
        for key, (kind, capabilities) in specs.items()
    }
    resources = {credential.ref: credential, connection.ref: connection}
    resources.update({value.ref: value for value in deployments.values()})
    repository, replays = Repository(resources), Replays()

    @asynccontextmanager
    async def scope():
        before = dict(repository.live)
        try:
            yield repository, replays
        except Exception:
            repository.live = before
            raise

    return (
        SystemConfigurationService(default_component_definition_registry(), scope),
        repository,
        replays,
        {key: value.ref.value for key, value in deployments.items()},
    )


@pytest.mark.asyncio
async def test_plan_is_non_mutating_and_apply_is_immediate_and_atomic() -> None:
    service, repository, replays, refs = setup()
    requested = desired(refs)
    token = service.concurrency_token(None)
    plan = await service.plan(requested)
    assert plan.valid and len(plan.changes) == 5
    assert repository.live == {} and replays.values == {} and repository.set_calls == 0

    applied = await service.apply(requested, token, "alice", "apply")
    assert len(applied.updated) == 5 and applied.unchanged == ()
    assert await service.get() == applied.configuration

    changed = desired(refs, voice="alloy")
    second = await service.apply(
        changed, service.concurrency_token(applied.configuration), "alice", "update"
    )
    assert second.updated == ("tts_defaults",)
    assert len(repository.live) == 5


@pytest.mark.asyncio
async def test_apply_replay_precedes_stale_aggregate_precondition() -> None:
    service, _, _, refs = setup()
    requested = desired(refs)
    token = service.concurrency_token(None)
    first = await service.apply(requested, token, "alice", "same")
    assert await service.apply(requested, token, "alice", "same") == first
    with pytest.raises(IdempotencyKeyReused):
        await service.apply(desired(refs, voice="changed"), token, "alice", "same")
    with pytest.raises(SystemConfigurationPreconditionFailed):
        await service.apply(requested, "stale", "alice", "stale")
    with pytest.raises(SystemConfigurationPreconditionFailed):
        await service.apply(requested, "*", "alice", "second-initial")


@pytest.mark.asyncio
async def test_apply_validates_deployment_kind_capabilities_and_usability() -> None:
    service, repository, _, refs = setup()
    llm_ref = ModelDeploymentRef(refs["llm"])
    repository.resources[llm_ref] = replace(
        repository.resources[llm_ref], deployment_kind=DeploymentKind.TTS
    )
    plan = await service.plan(desired(refs))
    assert not plan.valid and plan.errors[0].code == "wrong_deployment_kind"
    assert repository.live == {}
    with pytest.raises(SystemConfigurationError):
        await service.apply(desired(refs), "*", "alice", "invalid-apply")
    assert repository.live == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "path", "wrong_kind"),
    [
        ("stt", "stt_defaults.deployment_ref", DeploymentKind.TTS),
        ("llm", "llm_defaults.deployment_ref", DeploymentKind.STT),
        ("tts", "tts_defaults.deployment_ref", DeploymentKind.LLM),
        ("realtime", "realtime_defaults.deployment_ref", DeploymentKind.STT),
    ],
)
async def test_each_system_deployment_role_accepts_only_enabled_usable_matching_kind(
    role: str, path: str, wrong_kind: DeploymentKind
) -> None:
    service, repository, _, refs = setup()
    assert (await service.plan(desired(refs))).valid

    ref = ModelDeploymentRef(refs[role])
    deployment = repository.resources[ref]
    repository.resources[ref] = replace(deployment, deployment_kind=wrong_kind)
    wrong = await service.plan(desired(refs))
    assert any(
        error.path == path and error.code == "wrong_deployment_kind"
        for error in wrong.errors
    )

    repository.resources[ref] = replace(deployment, enabled=False)
    disabled = await service.plan(desired(refs))
    assert any(
        error.path == path and error.code == "deployment_unusable"
        for error in disabled.errors
    )

    repository.resources[ref] = deployment
    connection = repository.resources[deployment.connection_ref]
    repository.resources[deployment.connection_ref] = replace(connection, enabled=False)
    unusable = await service.plan(desired(refs))
    assert any(
        error.path == path and error.code == "deployment_unusable"
        for error in unusable.errors
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "capabilities", "path"),
    [
        ("stt", STTCapabilities(False, True), "stt_defaults.deployment_ref"),
        (
            "stt",
            STTCapabilities(True, False),
            "realtime_defaults.input_transcription.deployment_ref",
        ),
        ("llm", LLMCapabilities(False, True), "llm_defaults.temperature"),
        ("llm", LLMCapabilities(True, False), "llm_defaults.reasoning_effort"),
        (
            "realtime",
            RealtimeCapabilities(True, False),
            "realtime_defaults.turn_completion",
        ),
    ],
)
async def test_system_configuration_enforces_frozen_capability_relationships(
    role: str, capabilities: object, path: str
) -> None:
    service, repository, _, refs = setup()
    ref = ModelDeploymentRef(refs[role])
    repository.resources[ref] = replace(
        repository.resources[ref], capabilities=capabilities
    )

    plan = await service.plan(desired(refs))

    assert any(
        error.path == path and error.code == "unsupported_capability"
        for error in plan.errors
    )


@pytest.mark.asyncio
async def test_failure_in_final_component_rolls_back_complete_apply() -> None:
    service, repository, _, refs = setup()
    original_set = repository.set

    async def fail_on_policies(address, value, schema_version, actor):
        if str(address.kind) == "Policies":
            raise RuntimeError("final write failed")
        return await original_set(address, value, schema_version, actor)

    repository.set = fail_on_policies
    with pytest.raises(RuntimeError, match="final write failed"):
        await service.apply(
            desired(refs), service.concurrency_token(None), "alice", "failed"
        )
    assert repository.live == {}
