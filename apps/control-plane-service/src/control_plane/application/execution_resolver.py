from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from contracts.integration import HttpConnectionConfiguration

from control_plane.application.runtime_resolver import (
    RuntimeResolutionState,
    RuntimeResolver,
    StoredActiveRuntimeComponent,
)
from control_plane.domain.agent_components import TenantAgentValue
from control_plane.domain.capabilities import (
    TenantCapabilitiesConfig,
    TenantCapabilityProfile,
    derive_tool_name,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.knowledge_components import TenantKnowledgeValue
from control_plane.domain.post_call import TenantPostCallConfig
from control_plane.domain.prompt_components import ProfileSelection, PromptValue
from control_plane.domain.runtime_resolution import (
    ComponentProvenance,
    ResolutionFailureReason,
    ResolvedTenantAgent,
    RuntimeResolution,
    RuntimeResolutionError,
)


@dataclass(frozen=True, slots=True)
class ExecutionResolution:
    tenant_id: str
    runtime: RuntimeResolution
    agent: ResolvedTenantAgent
    prompts: dict[str, object]
    knowledge: dict[str, object]
    capabilities: tuple[dict[str, object], ...]
    post_call: tuple[dict[str, object], ...]
    handoff: tuple[Mapping[str, object], ...]
    phone_assignment: Mapping[str, object] | None
    provenance: dict[str, object]

    @property
    def architecture(self) -> str:
        return self.runtime.selected.architecture


def compose_instructions(*parts: str) -> str:
    """Legacy prompt ordering, without clock/runtime-only additions."""
    return "\n\n".join(part for part in parts if part)


class ExecutionResolver:
    def __init__(self, registry: ComponentRegistry, runtime: RuntimeResolver) -> None:
        self._registry, self._runtime = registry, runtime

    def resolve_state(
        self, tenant_id: str, state: RuntimeResolutionState
    ) -> ExecutionResolution:
        # Runtime selection is intentionally complete before non-runtime domains.
        runtime = self._runtime.resolve_state(tenant_id, state)
        agent = self._required(
            state,
            ComponentAddress(ComponentKind("agent.tenant"), TenantScope(tenant_id)),
            TenantAgentValue,
        )
        system = self._required(
            state,
            ComponentAddress(ComponentKind("prompt.system"), PlatformScope()),
            PromptValue,
        )
        selection = self._required(
            state,
            ComponentAddress(
                ComponentKind("prompt.profile.selection"), TenantScope(tenant_id)
            ),
            ProfileSelection,
            ResolutionFailureReason.MISSING_PROFILE_SELECTION,
        )
        profile = self._required(
            state,
            ComponentAddress(
                ComponentKind("prompt.profile"),
                ProfileScope(selection.value.profile_key),
            ),
            PromptValue,
            ResolutionFailureReason.MISSING_PROFILE,
        )
        tenant = self._required(
            state,
            ComponentAddress(ComponentKind("prompt.tenant"), TenantScope(tenant_id)),
            PromptValue,
        )
        knowledge = self._required(
            state,
            ComponentAddress(ComponentKind("knowledge.tenant"), TenantScope(tenant_id)),
            TenantKnowledgeValue,
        )
        capabilities = self._optional(
            state,
            ComponentAddress(
                ComponentKind("capabilities.tenant"), TenantScope(tenant_id)
            ),
            TenantCapabilitiesConfig,
            TenantCapabilitiesConfig(),
        )
        post_call = self._optional(
            state,
            ComponentAddress(ComponentKind("post_call.tenant"), TenantScope(tenant_id)),
            TenantPostCallConfig,
            TenantPostCallConfig(),
        )
        prompts = {
            "profile_key": selection.value.profile_key,
            "system": {
                "content": system.value.content,
                "provenance": self._provenance(system),
            },
            "profile": {
                "content": profile.value.content,
                "provenance": self._provenance(profile),
            },
            "tenant": {
                "content": tenant.value.content,
                "provenance": self._provenance(tenant),
            },
            "instructions": compose_instructions(
                system.value.content,
                profile.value.content,
                tenant.value.content,
                knowledge.value.content,
            ),
        }
        enabled = []
        for key, value in capabilities.value.capabilities.items():
            if isinstance(value, TenantCapabilityProfile) and value.enabled:
                self._validate_integration(
                    tenant_id, value.execution.integration_connection_ref.value, state
                )
                enabled.append(self._capability(key, value))
        actions = []
        for action in post_call.value.actions:
            self._validate_integration(
                tenant_id, action.execution.integration_connection_ref.value, state
            )
            actions.append(self._post_call(action))
        handoff = tuple(sorted(state.handoffs, key=lambda row: str(row["key"])))
        return ExecutionResolution(
            tenant_id,
            runtime,
            ResolvedTenantAgent(
                self._provenance(agent),
                agent.value.display_name,
                agent.value.agent_profile,
                agent.value.greeting,
                agent.value.conversation_scope,
                agent.value.locale,
                agent.value.timezone,
            ),
            prompts,
            {
                "content": knowledge.value.content,
                "provenance": self._provenance(knowledge),
            },
            tuple(enabled),
            tuple(actions),
            handoff,
            state.phone_assignment,
            {
                "agent": self._provenance(agent),
                "profile_selection": self._provenance(selection),
                "capabilities": self._provenance(capabilities)
                if capabilities.stored
                else None,
                "post_call": self._provenance(post_call) if post_call.stored else None,
            },
        )

    def _capability(
        self,
        key: str,
        value: TenantCapabilityProfile,
    ) -> dict[str, object]:
        execution = cast(dict[str, object], value.execution.model_dump(mode="json"))
        execution["connection_id"] = execution.pop("integration_connection_ref")
        return {
            "semantic_key": key,
            "semantic_version": 1,
            "tool_name": derive_tool_name(key),
            "enabled": value.enabled,
            "description": value.description,
            "announcement": value.announcement,
            "input_schema": value.agent_input_schema,
            "bindings": value.bindings,
            "input_constraints": value.input_constraints,
            "policy": value.business_policy,
            "execution": execution,
            "result_schema": value.result_schema,
        }

    def _post_call(self, action: Any) -> dict[str, object]:
        execution = cast(dict[str, object], action.execution.model_dump(mode="json"))
        execution["connection_id"] = execution.pop("integration_connection_ref")
        return {
            "action_id": action.action_id,
            "inputs": {
                key: value.model_dump(mode="json")
                for key, value in action.inputs.items()
            },
            "execution": execution,
        }

    @staticmethod
    def _validate_integration(
        tenant_id: str, ref: UUID, state: RuntimeResolutionState
    ) -> None:
        value = state.integrations.get(ref)
        if value is None or value["tenant_id"] != tenant_id:
            raise RuntimeResolutionError(
                ResolutionFailureReason.MISSING_RESOURCE,
                {"resource_type": "integration_connection", "resource_id": str(ref)},
            )
        if not value["enabled"] or value["integration_kind"] != "http":
            raise RuntimeResolutionError(
                ResolutionFailureReason.RESOURCE_DISABLED,
                {"resource_type": "integration_connection", "resource_id": str(ref)},
            )
        config = HttpConnectionConfiguration.model_validate(value["config"])
        if config.authentication.type != "none" and value["credential"] is None:
            raise RuntimeResolutionError(
                ResolutionFailureReason.MISSING_RESOURCE,
                {"resource_type": "credential", "integration_connection_id": str(ref)},
            )

    def _required(
        self,
        state: RuntimeResolutionState,
        address: ComponentAddress,
        expected: type,
        reason: ResolutionFailureReason = ResolutionFailureReason.MISSING_TENANT_COMPONENT,
    ):
        stored = state.components.get(address)
        if stored is None:
            raise RuntimeResolutionError(
                reason,
                {"component_kind": str(address.kind), "scope": address.scope.key},
            )
        return self._decode(stored, expected)

    def _optional(
        self,
        state: RuntimeResolutionState,
        address: ComponentAddress,
        expected: type,
        default: object,
    ):
        stored = state.components.get(address)
        return (
            _Decoded(None, default)
            if stored is None
            else self._decode(stored, expected)
        )

    def _decode(self, stored: StoredActiveRuntimeComponent, expected: type):
        try:
            definition = self._registry.resolve(stored.address)
            value = definition.deserialize(stored.value)
        except (ComponentError, ValueError) as error:
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {"component_kind": str(stored.address.kind)},
            ) from error
        if not isinstance(value, expected):
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {"component_kind": str(stored.address.kind)},
            )
        return _Decoded(stored, value)

    @staticmethod
    def _provenance(value: _Decoded) -> ComponentProvenance:
        assert value.stored is not None
        stored = value.stored
        return ComponentProvenance(
            str(stored.address.kind),
            stored.address.scope.type.value,
            stored.address.scope.key,
            stored.revision_id,
            stored.revision_number,
            stored.schema_version,
        )


@dataclass(frozen=True, slots=True)
class _Decoded:
    stored: StoredActiveRuntimeComponent | None
    value: object
