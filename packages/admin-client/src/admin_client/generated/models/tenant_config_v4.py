from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_config_v3 import AgentConfigV3
    from ..models.business_config import BusinessConfig
    from ..models.contact_config import ContactConfig
    from ..models.conversation_config import ConversationConfig
    from ..models.handoff_config import HandoffConfig
    from ..models.localization_config import LocalizationConfig
    from ..models.post_call_action import PostCallAction
    from ..models.tenant_config_v4_capabilities import TenantConfigV4Capabilities


T = TypeVar("T", bound="TenantConfigV4")


@_attrs_define
class TenantConfigV4:
    """
    Attributes:
        agent (AgentConfigV3):
        business (BusinessConfig):
        conversation (ConversationConfig):
        localization (LocalizationConfig):
        schema_version (Literal[4]):
        capabilities (TenantConfigV4Capabilities | Unset):
        contact (ContactConfig | Unset):
        handoff (HandoffConfig | Unset):
        post_call_actions (list[PostCallAction] | Unset):
    """

    agent: AgentConfigV3
    business: BusinessConfig
    conversation: ConversationConfig
    localization: LocalizationConfig
    schema_version: Literal[4]
    capabilities: TenantConfigV4Capabilities | Unset = UNSET
    contact: ContactConfig | Unset = UNSET
    handoff: HandoffConfig | Unset = UNSET
    post_call_actions: list[PostCallAction] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent.to_dict()

        business = self.business.to_dict()

        conversation = self.conversation.to_dict()

        localization = self.localization.to_dict()

        schema_version = self.schema_version

        capabilities: dict[str, Any] | Unset = UNSET
        if not isinstance(self.capabilities, Unset):
            capabilities = self.capabilities.to_dict()

        contact: dict[str, Any] | Unset = UNSET
        if not isinstance(self.contact, Unset):
            contact = self.contact.to_dict()

        handoff: dict[str, Any] | Unset = UNSET
        if not isinstance(self.handoff, Unset):
            handoff = self.handoff.to_dict()

        post_call_actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.post_call_actions, Unset):
            post_call_actions = []
            for post_call_actions_item_data in self.post_call_actions:
                post_call_actions_item = post_call_actions_item_data.to_dict()
                post_call_actions.append(post_call_actions_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent": agent,
                "business": business,
                "conversation": conversation,
                "localization": localization,
                "schema_version": schema_version,
            }
        )
        if capabilities is not UNSET:
            field_dict["capabilities"] = capabilities
        if contact is not UNSET:
            field_dict["contact"] = contact
        if handoff is not UNSET:
            field_dict["handoff"] = handoff
        if post_call_actions is not UNSET:
            field_dict["post_call_actions"] = post_call_actions

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_config_v3 import AgentConfigV3
        from ..models.business_config import BusinessConfig
        from ..models.contact_config import ContactConfig
        from ..models.conversation_config import ConversationConfig
        from ..models.handoff_config import HandoffConfig
        from ..models.localization_config import LocalizationConfig
        from ..models.post_call_action import PostCallAction
        from ..models.tenant_config_v4_capabilities import TenantConfigV4Capabilities

        d = dict(src_dict)
        agent = AgentConfigV3.from_dict(d.pop("agent"))

        business = BusinessConfig.from_dict(d.pop("business"))

        conversation = ConversationConfig.from_dict(d.pop("conversation"))

        localization = LocalizationConfig.from_dict(d.pop("localization"))

        schema_version = cast(Literal[4], d.pop("schema_version"))
        if schema_version != 4:
            raise ValueError(
                f"schema_version must match const 4, got '{schema_version}'"
            )

        _capabilities = d.pop("capabilities", UNSET)
        capabilities: TenantConfigV4Capabilities | Unset
        if isinstance(_capabilities, Unset):
            capabilities = UNSET
        else:
            capabilities = TenantConfigV4Capabilities.from_dict(_capabilities)

        _contact = d.pop("contact", UNSET)
        contact: ContactConfig | Unset
        if isinstance(_contact, Unset):
            contact = UNSET
        else:
            contact = ContactConfig.from_dict(_contact)

        _handoff = d.pop("handoff", UNSET)
        handoff: HandoffConfig | Unset
        if isinstance(_handoff, Unset):
            handoff = UNSET
        else:
            handoff = HandoffConfig.from_dict(_handoff)

        _post_call_actions = d.pop("post_call_actions", UNSET)
        post_call_actions: list[PostCallAction] | Unset = UNSET
        if _post_call_actions is not UNSET:
            post_call_actions = []
            for post_call_actions_item_data in _post_call_actions:
                post_call_actions_item = PostCallAction.from_dict(
                    post_call_actions_item_data
                )

                post_call_actions.append(post_call_actions_item)

        tenant_config_v4 = cls(
            agent=agent,
            business=business,
            conversation=conversation,
            localization=localization,
            schema_version=schema_version,
            capabilities=capabilities,
            contact=contact,
            handoff=handoff,
            post_call_actions=post_call_actions,
        )

        return tenant_config_v4
