from dataclasses import dataclass
from uuid import UUID, uuid4

from contracts.capability import RuntimeCapabilityDefinition
from contracts.runtime_bundle import (
    RuntimeBundle,
    RuntimeBundlePayload,
    RuntimeBundleProvenance,
    RuntimeCapabilityBinding,
    RuntimeCapabilityInputConstraint,
    RuntimeCapabilityPolicy,
    RuntimeGoogleSheetsExecution,
    RuntimeHandoffDestination,
    RuntimeHttpExecution,
    RuntimePostCallAction,
    RuntimePostCallInput,
    RuntimeTelephony,
    runtime_bundle_content_hash,
)
from contracts.tenant_components import (
    TenantAgentConfig,
    TenantCapabilitiesConfig,
    TenantCapabilityProfile,
    TenantKnowledgeConfig,
    TenantPostCallConfig,
    TenantPromptConfig,
    TenantTelephonyConfig,
)
from contracts.voice import HandoffDestinationDefinition, VoiceAgentPrompt
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    PlatformRuntimePolicy,
    TenantRuntimeOverride,
    model_supports_reasoning,
)

from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    resolve_capability,
)


@dataclass(frozen=True, slots=True)
class CompiledRuntimeBundle:
    """Pure output of release assembly; persistence is owned by the orchestrator."""

    bundle: RuntimeBundle


@dataclass(frozen=True, slots=True)
class PlatformBundleInput:
    """Already-resolved immutable platform inputs; compiler never loads them."""

    runtime_revision_id: UUID
    system_prompt_revision_id: UUID
    profile_prompt_revision_id: UUID
    runtime_policy: PlatformRuntimePolicy
    system_prompt: str
    profile_prompt: str


def compile_tenant_runtime_bundle(
    *,
    tenant_id: UUID,
    runtime_revision_id: UUID,
    runtime: TenantRuntimeOverride,
    agent_revision_id: UUID,
    agent: TenantAgentConfig,
    prompt_revision_id: UUID,
    prompt: TenantPromptConfig,
    knowledge_revision_id: UUID,
    knowledge: TenantKnowledgeConfig,
    capabilities_revision_id: UUID,
    capabilities: TenantCapabilitiesConfig,
    post_call_revision_id: UUID,
    post_call: TenantPostCallConfig,
    telephony_revision_id: UUID,
    telephony: TenantTelephonyConfig,
    platform: PlatformBundleInput,
    compiler_build_id: str,
) -> CompiledRuntimeBundle:
    """Pure release compiler: all inputs are sealed values or exact references."""

    voice_runtime = _effective_voice_runtime(platform.runtime_policy, runtime, agent)
    resolved_capabilities = [
        (profile, resolve_capability(key, profile))
        for key, profile in capabilities.capabilities.items()
        if isinstance(profile, TenantCapabilityProfile) and profile.enabled
    ]
    tool_names = [definition.tool_name for _, definition in resolved_capabilities]
    duplicates = sorted({name for name in tool_names if tool_names.count(name) > 1})
    if duplicates:
        raise CapabilityValidationError(
            "duplicate_tool_name",
            f"Capability tool names must be unique: {', '.join(duplicates)}",
            "capabilities",
        )
    bindings = _capability_bindings(resolved_capabilities)
    post_call_actions = _post_call_actions(post_call)
    integration_ids = sorted(
        {binding.execution.connection_id for binding in bindings}
        | {action.execution.connection_id for action in post_call_actions},
        key=str,
    )
    runtime_telephony = RuntimeTelephony(
        caller_number=telephony.phone_number,
        handoff_destinations={
            key: RuntimeHandoffDestination(
                description=value.description, phone_number=value.phone_number
            )
            for key, value in agent.handoff.destinations.items()
        },
    )
    payload = RuntimeBundlePayload(
        voice_runtime=voice_runtime,
        locale=agent.localization.default_locale,
        timezone=agent.localization.timezone,
        agent_display_name=agent.agent.display_name,
        agent_profile=agent.agent.profile,
        greeting=agent.agent.greeting,
        conversation_scope=agent.conversation.scope.value,
        prompt=VoiceAgentPrompt(
            system_prompt=platform.system_prompt,
            profile_prompt=platform.profile_prompt,
            tenant_prompt=prompt.text,
            knowledge_context=knowledge.inline_context,
            knowledge_base_revision_id=knowledge.knowledge_base_revision_id,
        ),
        capabilities=[definition for _, definition in resolved_capabilities],
        capability_bindings=bindings,
        post_call_actions=post_call_actions,
        telephony=runtime_telephony,
        handoff_destinations={
            key: HandoffDestinationDefinition(description=value.description)
            for key, value in agent.handoff.destinations.items()
        },
    )
    return compile_runtime_bundle(
        tenant_id=tenant_id,
        payload=payload,
        provenance=RuntimeBundleProvenance(
            runtime_revision_id=runtime_revision_id,
            agent_revision_id=agent_revision_id,
            prompt_revision_id=prompt_revision_id,
            knowledge_revision_id=knowledge_revision_id,
            capabilities_revision_id=capabilities_revision_id,
            post_call_revision_id=post_call_revision_id,
            telephony_revision_id=telephony_revision_id,
            platform_runtime_revision_id=platform.runtime_revision_id,
            system_prompt_revision_id=platform.system_prompt_revision_id,
            profile_prompt_revision_id=platform.profile_prompt_revision_id,
            integration_connection_ids=integration_ids,
            knowledge_artifact_id=knowledge.artifact_id,
        ),
        compiler_build_id=compiler_build_id,
    )


def _effective_voice_runtime(
    policy: PlatformRuntimePolicy,
    override: TenantRuntimeOverride,
    agent: TenantAgentConfig,
) -> EffectiveVoiceRuntime:
    payload = policy.model_dump(mode="json")
    if override.llm is not None:
        payload["llm"]["model"] = override.llm.model
        if override.llm.temperature is not None:
            payload["llm"]["temperature"] = override.llm.temperature
        elif model_supports_reasoning(override.llm.model):
            payload["llm"]["temperature"] = None
        if override.llm.reasoning_effort is not None:
            payload["llm"]["reasoning_effort"] = override.llm.reasoning_effort
        elif not model_supports_reasoning(override.llm.model):
            payload["llm"]["reasoning_effort"] = "none"
    if override.tts is not None:
        payload["tts"]["voice_id"] = override.tts.voice_id
    payload["stt"]["keyterms"] = override.stt.keyterms if override.stt else []
    return EffectiveVoiceRuntime.model_validate(
        {"locale": agent.localization.default_locale, **payload}
    )


def _capability_bindings(
    capabilities: list[tuple[TenantCapabilityProfile, RuntimeCapabilityDefinition]],
) -> list[RuntimeCapabilityBinding]:
    bindings: list[RuntimeCapabilityBinding] = []
    for profile, definition in capabilities:
        execution = profile.execution
        runtime_execution: RuntimeGoogleSheetsExecution | RuntimeHttpExecution
        if execution.plan_type == "google_sheets.append_values.v1":
            runtime_execution = RuntimeGoogleSheetsExecution(
                connection_id=execution.connection_id,
                spreadsheet_id=execution.spreadsheet_id,
                sheet_name=execution.sheet_name,
                append_range=execution.append_range,
                value_input_option=execution.value_input_option,
                lookup_range=execution.idempotency.lookup_range,
                operation_id_column_index=execution.idempotency.operation_id_column_index,
                request_mapping=execution.request_mapping,
            )
        else:
            runtime_execution = RuntimeHttpExecution(
                connection_id=execution.connection_id,
                method=execution.method,
                path=execution.path,
                query=execution.query,
                headers=execution.headers,
                request=execution.request,
                response=execution.response,
                timeout_seconds=execution.timeout_seconds,
                success_statuses=execution.success_statuses,
                result_schema=execution.result_schema,
            )
        bindings.append(
            RuntimeCapabilityBinding(
                semantic_key=definition.semantic_key,
                semantic_version=definition.semantic_version,
                tool_name=definition.tool_name,
                enabled=True,
                input_schema=profile.agent_input_schema,
                bindings=profile.bindings,
                input_constraints=[
                    RuntimeCapabilityInputConstraint.model_validate(
                        constraint.model_dump(mode="json")
                    )
                    for constraint in profile.input_constraints
                ],
                policy=RuntimeCapabilityPolicy(
                    **profile.business_policy.model_dump(mode="json")
                ),
                execution=runtime_execution,
            )
        )
    return bindings


def _post_call_actions(
    post_call: TenantPostCallConfig,
) -> list[RuntimePostCallAction]:
    return [
        RuntimePostCallAction(
            action_id=action.action_id,
            inputs={
                key: RuntimePostCallInput(**value.model_dump(mode="json"))
                for key, value in action.inputs.items()
            },
            execution=RuntimeHttpExecution(
                connection_id=action.execution.connection_id,
                method=action.execution.method,
                path=action.execution.path,
                query=action.execution.query,
                headers=action.execution.headers,
                request=action.execution.request,
                response=action.execution.response,
                timeout_seconds=action.execution.timeout_seconds,
            ),
        )
        for action in post_call.actions
    ]


def compile_runtime_bundle(
    *,
    tenant_id: UUID,
    payload: RuntimeBundlePayload,
    provenance: RuntimeBundleProvenance,
    compiler_build_id: str,
) -> CompiledRuntimeBundle:
    return CompiledRuntimeBundle(
        bundle=RuntimeBundle(
            id=uuid4(),
            tenant_id=tenant_id,
            payload=payload,
            provenance=provenance,
            content_hash=runtime_bundle_content_hash(payload, provenance),
            compiler_build_id=compiler_build_id,
        )
    )
