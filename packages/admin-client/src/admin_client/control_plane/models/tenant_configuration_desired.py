from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.actions_availability import ActionsAvailability
    from ..models.actions_definition_input import ActionsDefinitionInput
    from ..models.agent_identity import AgentIdentity
    from ..models.architecture import Architecture
    from ..models.business_identity import BusinessIdentity
    from ..models.interaction_mode_reference import InteractionModeReference
    from ..models.knowledge import Knowledge
    from ..models.profile_reference import ProfileReference
    from ..models.runtime_overrides import RuntimeOverrides
    from ..models.tenant_prompt import TenantPrompt


T = TypeVar("T", bound="TenantConfigurationDesired")


@_attrs_define
class TenantConfigurationDesired:
    """
    Attributes:
        actions_availability (ActionsAvailability):
        actions_definition (ActionsDefinitionInput):
        agent_identity (AgentIdentity):
        architecture (Architecture):
        business_identity (BusinessIdentity):
        interaction_mode_reference (InteractionModeReference):
        knowledge (Knowledge):
        profile_reference (ProfileReference):
        runtime_overrides (RuntimeOverrides):
        tenant_prompt (TenantPrompt):
    """

    actions_availability: ActionsAvailability
    actions_definition: ActionsDefinitionInput
    agent_identity: AgentIdentity
    architecture: Architecture
    business_identity: BusinessIdentity
    interaction_mode_reference: InteractionModeReference
    knowledge: Knowledge
    profile_reference: ProfileReference
    runtime_overrides: RuntimeOverrides
    tenant_prompt: TenantPrompt

    def to_dict(self) -> dict[str, Any]:
        actions_availability = self.actions_availability.to_dict()

        actions_definition = self.actions_definition.to_dict()

        agent_identity = self.agent_identity.to_dict()

        architecture = self.architecture.to_dict()

        business_identity = self.business_identity.to_dict()

        interaction_mode_reference = self.interaction_mode_reference.to_dict()

        knowledge = self.knowledge.to_dict()

        profile_reference = self.profile_reference.to_dict()

        runtime_overrides = self.runtime_overrides.to_dict()

        tenant_prompt = self.tenant_prompt.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "actions_availability": actions_availability,
                "actions_definition": actions_definition,
                "agent_identity": agent_identity,
                "architecture": architecture,
                "business_identity": business_identity,
                "interaction_mode_reference": interaction_mode_reference,
                "knowledge": knowledge,
                "profile_reference": profile_reference,
                "runtime_overrides": runtime_overrides,
                "tenant_prompt": tenant_prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.actions_availability import ActionsAvailability
        from ..models.actions_definition_input import ActionsDefinitionInput
        from ..models.agent_identity import AgentIdentity
        from ..models.architecture import Architecture
        from ..models.business_identity import BusinessIdentity
        from ..models.interaction_mode_reference import InteractionModeReference
        from ..models.knowledge import Knowledge
        from ..models.profile_reference import ProfileReference
        from ..models.runtime_overrides import RuntimeOverrides
        from ..models.tenant_prompt import TenantPrompt

        d = dict(src_dict)
        actions_availability = ActionsAvailability.from_dict(
            d.pop("actions_availability")
        )

        actions_definition = ActionsDefinitionInput.from_dict(
            d.pop("actions_definition")
        )

        agent_identity = AgentIdentity.from_dict(d.pop("agent_identity"))

        architecture = Architecture.from_dict(d.pop("architecture"))

        business_identity = BusinessIdentity.from_dict(d.pop("business_identity"))

        interaction_mode_reference = InteractionModeReference.from_dict(
            d.pop("interaction_mode_reference")
        )

        knowledge = Knowledge.from_dict(d.pop("knowledge"))

        profile_reference = ProfileReference.from_dict(d.pop("profile_reference"))

        runtime_overrides = RuntimeOverrides.from_dict(d.pop("runtime_overrides"))

        tenant_prompt = TenantPrompt.from_dict(d.pop("tenant_prompt"))

        tenant_configuration_desired = cls(
            actions_availability=actions_availability,
            actions_definition=actions_definition,
            agent_identity=agent_identity,
            architecture=architecture,
            business_identity=business_identity,
            interaction_mode_reference=interaction_mode_reference,
            knowledge=knowledge,
            profile_reference=profile_reference,
            runtime_overrides=runtime_overrides,
            tenant_prompt=tenant_prompt,
        )

        return tenant_configuration_desired
