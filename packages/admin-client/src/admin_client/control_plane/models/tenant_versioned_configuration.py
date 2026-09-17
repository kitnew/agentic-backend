from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.prompt_state_actions_definition import PromptStateActionsDefinition
    from ..models.prompt_state_agent_identity import PromptStateAgentIdentity
    from ..models.prompt_state_business_identity import PromptStateBusinessIdentity
    from ..models.prompt_state_knowledge import PromptStateKnowledge
    from ..models.prompt_state_tenant_prompt import PromptStateTenantPrompt


T = TypeVar("T", bound="TenantVersionedConfiguration")


@_attrs_define
class TenantVersionedConfiguration:
    """
    Attributes:
        actions_definition (PromptStateActionsDefinition):
        agent_identity (PromptStateAgentIdentity):
        business_identity (PromptStateBusinessIdentity):
        knowledge (PromptStateKnowledge):
        tenant_prompt (PromptStateTenantPrompt):
    """

    actions_definition: PromptStateActionsDefinition
    agent_identity: PromptStateAgentIdentity
    business_identity: PromptStateBusinessIdentity
    knowledge: PromptStateKnowledge
    tenant_prompt: PromptStateTenantPrompt

    def to_dict(self) -> dict[str, Any]:
        actions_definition = self.actions_definition.to_dict()

        agent_identity = self.agent_identity.to_dict()

        business_identity = self.business_identity.to_dict()

        knowledge = self.knowledge.to_dict()

        tenant_prompt = self.tenant_prompt.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "actions_definition": actions_definition,
                "agent_identity": agent_identity,
                "business_identity": business_identity,
                "knowledge": knowledge,
                "tenant_prompt": tenant_prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_state_actions_definition import (
            PromptStateActionsDefinition,
        )
        from ..models.prompt_state_agent_identity import PromptStateAgentIdentity
        from ..models.prompt_state_business_identity import PromptStateBusinessIdentity
        from ..models.prompt_state_knowledge import PromptStateKnowledge
        from ..models.prompt_state_tenant_prompt import PromptStateTenantPrompt

        d = dict(src_dict)
        actions_definition = PromptStateActionsDefinition.from_dict(
            d.pop("actions_definition")
        )

        agent_identity = PromptStateAgentIdentity.from_dict(d.pop("agent_identity"))

        business_identity = PromptStateBusinessIdentity.from_dict(
            d.pop("business_identity")
        )

        knowledge = PromptStateKnowledge.from_dict(d.pop("knowledge"))

        tenant_prompt = PromptStateTenantPrompt.from_dict(d.pop("tenant_prompt"))

        tenant_versioned_configuration = cls(
            actions_definition=actions_definition,
            agent_identity=agent_identity,
            business_identity=business_identity,
            knowledge=knowledge,
            tenant_prompt=tenant_prompt,
        )

        return tenant_versioned_configuration
