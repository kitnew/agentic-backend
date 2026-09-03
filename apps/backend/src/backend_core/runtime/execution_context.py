from typing import Any, Literal, cast
from uuid import UUID

from contracts import (
    HandoffDestinationDefinition,
    RuntimeCapabilityBinding,
    RuntimeCapabilityDefinition,
    RuntimePostCallAction,
    VoiceAgentPrompt,
    VoiceAgentRuntimeContext,
)
from contracts.voice_runtime import EffectiveVoiceRuntime
from pydantic import ValidationError

from backend_core.modules.calls.models import CallSession
from backend_core.platform.control_plane import ControlPlaneClient


class RuntimeContextUnavailableError(ValueError):
    pass


class ExecutionContextReader:
    """The sole Backend execution reader for snapshot-pinned calls."""

    def __init__(self, client: ControlPlaneClient) -> None:
        self._client = client

    async def read(self, call: CallSession) -> VoiceAgentRuntimeContext:
        if call.execution_snapshot_id is None:
            raise RuntimeContextUnavailableError("call has no execution snapshot")
        snapshot = await self._client.get_execution_snapshot(call.execution_snapshot_id)
        if snapshot.tenant_id != str(call.tenant_id):
            raise ValueError("execution snapshot tenant mismatch")
        execution = snapshot.execution
        agent = snapshot.agent or {}
        prompts = execution.get("prompts", {})
        if not isinstance(prompts, dict):
            raise TypeError("execution snapshot prompts are invalid")
        runtime = _effective_runtime(snapshot.runtime, str(agent["locale"]))
        try:
            prompt = VoiceAgentPrompt(
                system_prompt=str(_nested(prompts, "system", "content")),
                profile_prompt=str(_nested(prompts, "profile", "content")),
                tenant_prompt=str(_nested(prompts, "tenant", "content")),
                knowledge_context=str(_nested(execution, "knowledge", "content")),
            )
            capabilities = [
                RuntimeCapabilityDefinition.model_validate(_capability(item))
                for item in _list(execution.get("capabilities"))
            ]
            handoff = {
                str(item["key"]): HandoffDestinationDefinition(
                    description=str(item["description"]),
                    ref=UUID(str(item["ref"])) if item.get("ref") else None,
                    key=str(item["key"]),
                    generation=int(item["generation"])
                    if item.get("generation")
                    else None,
                )
                for item in _list(execution.get("handoff"))
                if isinstance(item, dict) and "key" in item and "description" in item
            }
            return VoiceAgentRuntimeContext(
                call_session_id=call.id,
                execution_snapshot_id=snapshot.snapshot_id,
                architecture=cast(
                    Literal["cascade", "realtime"], snapshot.architecture
                ),
                voice_runtime=runtime,
                snapshot_runtime=snapshot.runtime,
                room_name=call.room_name,
                locale=str(agent["locale"]),
                timezone=str(agent["timezone"]),
                agent_display_name=str(agent["display_name"]),
                agent_profile=str(agent["agent_profile"]),
                greeting=str(agent["greeting"]),
                conversation_scope=str(agent["conversation_scope"]),
                prompt=prompt,
                capabilities=capabilities,
                handoff_destinations=handoff,
                voice_runtime_revision_id=UUID(str(agent["component"]["revision_id"])),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise RuntimeError("execution snapshot is invalid") from error

    async def snapshot(self, call: CallSession):
        if call.execution_snapshot_id is None:
            raise ValueError("call has no execution snapshot")
        snapshot = await self._client.get_execution_snapshot(call.execution_snapshot_id)
        if snapshot.tenant_id != str(call.tenant_id):
            raise ValueError("execution snapshot tenant mismatch")
        return snapshot

    async def capability(
        self, call: CallSession, semantic_key: str
    ) -> RuntimeCapabilityBinding:
        snapshot = await self.snapshot(call)
        for item in _list(snapshot.execution.get("capabilities")):
            if isinstance(item, dict) and semantic_key in {
                item.get("semantic_key"),
                item.get("tool_name"),
            }:
                return RuntimeCapabilityBinding.model_validate(item)
        raise ValueError("capability is not in execution snapshot")

    async def post_call_actions(self, call: CallSession) -> list[RuntimePostCallAction]:
        snapshot = await self.snapshot(call)
        return [
            RuntimePostCallAction.model_validate(item)
            for item in _list(snapshot.execution.get("post_call"))
        ]

    async def handoff(
        self, call: CallSession
    ) -> dict[str, HandoffDestinationDefinition]:
        snapshot = await self.snapshot(call)
        return {
            str(item["key"]): HandoffDestinationDefinition(
                ref=UUID(str(item["ref"])),
                key=str(item["key"]),
                description=str(item["description"]),
                generation=int(item["generation"]),
            )
            for item in _list(snapshot.execution.get("handoff"))
            if isinstance(item, dict) and item.get("key") and item.get("ref")
        }


def _nested(value: dict[str, Any], *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _capability(value: object) -> object:
    if not isinstance(value, dict):
        return value
    return {
        key: value[key]
        for key in (
            "semantic_key",
            "semantic_version",
            "tool_name",
            "description",
            "announcement",
            "input_schema",
            "requires_confirmation",
        )
        if key in value
    }


def _effective_runtime(
    value: dict[str, Any], locale: str
) -> EffectiveVoiceRuntime | None:
    if value.get("architecture") != "cascade":
        return None
    llm, stt, tts = value["llm"], value["stt"], value["tts"]
    policy = value["execution"]["policy"]
    deployment = lambda item: item["resource"]["deployment"]["deployment_config"]
    connection = lambda item: item["resource"]["connection"]["provider_kind"]
    commit = policy["stt_commit"]
    tuning = commit.get("provider_vad", {})
    return EffectiveVoiceRuntime.model_validate(
        {
            "llm": {
                "provider": connection(llm),
                "model": deployment(llm).get(
                    "model", deployment(llm).get("deployment_name", "")
                ),
                "max_completion_tokens": llm["parameters"]["max_completion_tokens"],
                "temperature": llm["parameters"].get("temperature"),
                "reasoning_effort": llm["parameters"].get("reasoning_effort"),
            },
            "stt": {
                "provider": connection(stt),
                "model": deployment(stt).get(
                    "model_id", deployment(stt).get("model", "")
                ),
                "keyterms": stt["speech_hints"]["keyterms"]["values"],
                "server_vad": {
                    "silence_threshold_seconds": tuning.get(
                        "silence_threshold_seconds", 0.5
                    ),
                    "activity_threshold": tuning.get("threshold", 0.5),
                    "min_speech_ms": tuning.get("min_speech_ms", 100),
                    "min_silence_ms": tuning.get("min_silence_ms", 250),
                },
                "local_vad_commit": {"enabled": commit["strategy"] == "local_vad"},
            },
            "tts": {
                "provider": connection(tts),
                "model": deployment(tts).get(
                    "model_id", deployment(tts).get("model", "")
                ),
                "voice_id": tts["voice"],
                "min_sentence_chars": tts["defaults"]["min_sentence_chars"],
            },
            "local_vad": policy["speech_activity"],
            "turn": {
                "detection": "stt",
                "min_endpointing_delay_seconds": policy["endpointing"][
                    "min_delay_seconds"
                ],
                "max_endpointing_delay_seconds": policy["endpointing"][
                    "max_delay_seconds"
                ],
            },
            "interruption": policy["interruption"],
            "response_scheduling": policy["response_scheduling"],
            "locale": locale,
        }
    )
