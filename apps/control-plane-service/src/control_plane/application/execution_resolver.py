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
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import ComponentError
from control_plane.domain.frozen_components import (
    ActionsAvailability,
    ActionsDefinition,
    AgentPersonality,
    BusinessInfo,
    Knowledge,
    PostCallActionDefinition,
    ProfilePrompt,
    ProfileReference,
    RuntimeActionDefinition,
    SystemPrompt,
    TenantPrompt,
)
from control_plane.domain.live_components import LiveComponentState
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
    handoff: tuple[Mapping[str, object], ...]
    provenance: dict[str, object]
    actions: tuple[dict[str, object], ...]
    integration_bindings: Mapping[str, UUID]

    @property
    def architecture(self) -> str:
        return self.runtime.selected.architecture


def compose_instructions(*parts: str) -> str:
    """Legacy prompt ordering, without clock/runtime-only additions."""
    return "\n\n".join(part for part in parts if part)


class ExecutionResolver:
    def __init__(
        self, registry: ComponentDefinitionRegistry, runtime: RuntimeResolver
    ) -> None:
        self._registry, self._runtime = registry, runtime

    def resolve_state(
        self, tenant_id: str, state: RuntimeResolutionState
    ) -> ExecutionResolution:
        # Runtime selection is intentionally complete before non-runtime domains.
        runtime = self._runtime.resolve_state(tenant_id, state)
        agent = self._required(
            state,
            ComponentAddress(ComponentKind("AgentPersonality"), TenantScope(tenant_id)),
            AgentPersonality,
        )
        business = self._required(
            state,
            ComponentAddress(ComponentKind("BusinessInfo"), TenantScope(tenant_id)),
            BusinessInfo,
        )
        system = self._required(
            state,
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            SystemPrompt,
        )
        selection = self._required_live(
            state,
            ComponentAddress(ComponentKind("ProfileReference"), TenantScope(tenant_id)),
            ProfileReference,
            ResolutionFailureReason.MISSING_PROFILE_SELECTION,
        )
        profile = self._required(
            state,
            ComponentAddress(
                ComponentKind("ProfilePrompt"),
                ProfileScope(selection.value.profile_key),
            ),
            ProfilePrompt,
            ResolutionFailureReason.MISSING_PROFILE,
        )
        tenant = self._required(
            state,
            ComponentAddress(ComponentKind("TenantPrompt"), TenantScope(tenant_id)),
            TenantPrompt,
        )
        knowledge = self._required(
            state,
            ComponentAddress(ComponentKind("Knowledge"), TenantScope(tenant_id)),
            Knowledge,
        )
        definitions = self._required(
            state,
            ComponentAddress(
                ComponentKind("ActionsDefinition"), TenantScope(tenant_id)
            ),
            ActionsDefinition,
        )
        availability = self._required_live(
            state,
            ComponentAddress(
                ComponentKind("ActionsAvailability"), TenantScope(tenant_id)
            ),
            ActionsAvailability,
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
        unknown = set(availability.value.actions) - set(definitions.value.actions)
        if unknown:
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {
                    "component_kind": "ActionsAvailability",
                    "unknown_actions": sorted(unknown),
                },
            )
        target_actions = []
        integration_bindings: dict[str, UUID] = {}
        for key, value in definitions.value.actions.items():
            if not availability.value.actions.get(key, False):
                continue
            integration = self._validate_integration(
                tenant_id, value.execution.integration_key, state
            )
            integration_bindings[value.execution.integration_key] = cast(
                UUID, integration["id"]
            )
            target_actions.append(self._target_action(key, value))
        handoff = tuple(sorted(state.handoffs, key=lambda row: str(row["key"])))
        return ExecutionResolution(
            tenant_id,
            runtime,
            ResolvedTenantAgent(
                self._provenance(agent),
                agent.value.display_name,
                agent.value.identity,
                agent.value.greeting,
                agent.value.conversation_scope,
                business.value.localization.default_locale,
                business.value.localization.timezone,
            ),
            prompts,
            {
                "content": knowledge.value.content,
                "provenance": self._provenance(knowledge),
            },
            handoff,
            {
                "agent": self._provenance(agent),
                "profile_selection": self._provenance(selection),
                "business_info": self._provenance(business),
                "actions_definition": self._provenance(definitions),
                "actions_availability": self._provenance(availability),
            },
            tuple(target_actions),
            integration_bindings,
        )

    @staticmethod
    def _target_action(
        key: str, value: RuntimeActionDefinition | PostCallActionDefinition
    ) -> dict[str, object]:
        raw = cast(dict[str, object], value.model_dump(mode="json"))
        execution = cast(dict[str, object], raw.pop("execution"))
        integration_key = cast(str, execution.pop("integration_key"))
        phase = cast(str, raw.pop("phase"))
        return {
            "key": key,
            "phase": phase,
            "definition": raw,
            "execution_plan": execution,
            "integration": {"semantic_key": integration_key},
        }

    @staticmethod
    def _validate_integration(
        tenant_id: str, key: str, state: RuntimeResolutionState
    ) -> Mapping[str, object]:
        value = next(
            (item for item in state.integrations.values() if item.get("key") == key),
            None,
        )
        if value is None or value["tenant_id"] != tenant_id:
            raise RuntimeResolutionError(
                ResolutionFailureReason.MISSING_RESOURCE,
                {"resource_type": "integration_connection", "integration_key": key},
            )
        if not value["enabled"] or value["integration_kind"] != "http":
            raise RuntimeResolutionError(
                ResolutionFailureReason.RESOURCE_DISABLED,
                {"resource_type": "integration_connection", "integration_key": key},
            )
        config = HttpConnectionConfiguration.model_validate(value["config"])
        credential = value["credential"]
        if config.authentication.type == "none":
            if credential is not None:
                raise RuntimeResolutionError(
                    ResolutionFailureReason.CURRENT_STATE_INVALID,
                    {
                        "resource_type": "integration_connection",
                        "integration_key": key,
                    },
                )
            return value
        if not isinstance(credential, Mapping):
            raise RuntimeResolutionError(
                ResolutionFailureReason.MISSING_RESOURCE,
                {"resource_type": "credential", "integration_key": key},
            )
        if (
            credential["scope_type"] == "tenant"
            and credential["tenant_id"] != tenant_id
        ):
            raise RuntimeResolutionError(
                ResolutionFailureReason.CROSS_TENANT_RESOURCE,
                {"resource_type": "credential", "integration_key": key},
            )
        if (
            credential["status"] != "active"
            or credential["active_version_id"] is None
            or credential["active_version_number"] is None
        ):
            raise RuntimeResolutionError(
                ResolutionFailureReason.CREDENTIAL_REVOKED,
                {"resource_type": "credential", "integration_key": key},
            )
        return value

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

    def _required_live(
        self,
        state: RuntimeResolutionState,
        address: ComponentAddress,
        expected: type,
        reason: ResolutionFailureReason = ResolutionFailureReason.MISSING_TENANT_COMPONENT,
    ):
        stored = state.live_components.get(address)
        if stored is None:
            raise RuntimeResolutionError(
                reason,
                {"component_kind": str(address.kind), "scope": address.scope.key},
            )
        try:
            definition = self._registry.resolve(address)
            value = definition.deserialize(stored.value)
        except (ComponentError, ValueError) as error:
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {"component_kind": str(address.kind)},
            ) from error
        if not isinstance(value, expected):
            raise RuntimeResolutionError(
                ResolutionFailureReason.CURRENT_STATE_INVALID,
                {"component_kind": str(address.kind)},
            )
        return _DecodedLive(stored, value)

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
    def _provenance(value: _Decoded | _DecodedLive) -> ComponentProvenance:
        assert value.stored is not None
        stored = value.stored
        if isinstance(stored, LiveComponentState):
            return ComponentProvenance(
                str(stored.address.kind),
                stored.address.scope.type.value,
                stored.address.scope.key,
                None,
                None,
                stored.schema_version,
            )
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


@dataclass(frozen=True, slots=True)
class _DecodedLive:
    stored: LiveComponentState[Any]
    value: object
