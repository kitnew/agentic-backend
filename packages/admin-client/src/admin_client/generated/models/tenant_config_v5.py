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
    from ..models.localization_config import LocalizationConfig
    from ..models.post_call_action import PostCallAction
    from ..models.tenant_config_v5_capabilities import TenantConfigV5Capabilities
    from ..models.tenant_telephony_config import TenantTelephonyConfig


T = TypeVar("T", bound="TenantConfigV5")


@_attrs_define
class TenantConfigV5:
    """
    Attributes:
        agent (AgentConfigV3):
        business (BusinessConfig):
        conversation (ConversationConfig):
        localization (LocalizationConfig):
        schema_version (Literal[5]):
        capabilities (TenantConfigV5Capabilities | Unset):
        contact (ContactConfig | Unset):
        post_call_actions (list[PostCallAction] | Unset):
        telephony (TenantTelephonyConfig | Unset):
    """

    agent: AgentConfigV3
    business: BusinessConfig
    conversation: ConversationConfig
    localization: LocalizationConfig
    schema_version: Literal[5]
    capabilities: TenantConfigV5Capabilities | Unset = UNSET
    contact: ContactConfig | Unset = UNSET
    post_call_actions: list[PostCallAction] | Unset = UNSET
    telephony: TenantTelephonyConfig | Unset = UNSET

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

        post_call_actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.post_call_actions, Unset):
            post_call_actions = []
            for post_call_actions_item_data in self.post_call_actions:
                post_call_actions_item = post_call_actions_item_data.to_dict()
                post_call_actions.append(post_call_actions_item)

        telephony: dict[str, Any] | Unset = UNSET
        if not isinstance(self.telephony, Unset):
            telephony = self.telephony.to_dict()

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
        if post_call_actions is not UNSET:
            field_dict["post_call_actions"] = post_call_actions
        if telephony is not UNSET:
            field_dict["telephony"] = telephony

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_config_v3 import AgentConfigV3
        from ..models.business_config import BusinessConfig
        from ..models.contact_config import ContactConfig
        from ..models.conversation_config import ConversationConfig
        from ..models.localization_config import LocalizationConfig
        from ..models.post_call_action import PostCallAction
        from ..models.tenant_config_v5_capabilities import TenantConfigV5Capabilities
        from ..models.tenant_telephony_config import TenantTelephonyConfig

        d = dict(src_dict)
        agent = AgentConfigV3.from_dict(d.pop("agent"))

        business = BusinessConfig.from_dict(d.pop("business"))

        conversation = ConversationConfig.from_dict(d.pop("conversation"))

        localization = LocalizationConfig.from_dict(d.pop("localization"))

        schema_version = cast(Literal[5], d.pop("schema_version"))
        if schema_version != 5:
            raise ValueError(
                f"schema_version must match const 5, got '{schema_version}'"
            )

        _capabilities = d.pop("capabilities", UNSET)
        capabilities: TenantConfigV5Capabilities | Unset
        if isinstance(_capabilities, Unset):
            capabilities = UNSET
        else:
            capabilities = TenantConfigV5Capabilities.from_dict(_capabilities)

        _contact = d.pop("contact", UNSET)
        contact: ContactConfig | Unset
        if isinstance(_contact, Unset):
            contact = UNSET
        else:
            contact = ContactConfig.from_dict(_contact)

        _post_call_actions = d.pop("post_call_actions", UNSET)
        post_call_actions: list[PostCallAction] | Unset = UNSET
        if _post_call_actions is not UNSET:
            post_call_actions = []
            for post_call_actions_item_data in _post_call_actions:
                post_call_actions_item = PostCallAction.from_dict(
                    post_call_actions_item_data
                )

                post_call_actions.append(post_call_actions_item)

        _telephony = d.pop("telephony", UNSET)
        telephony: TenantTelephonyConfig | Unset
        if isinstance(_telephony, Unset):
            telephony = UNSET
        else:
            telephony = TenantTelephonyConfig.from_dict(_telephony)

        tenant_config_v5 = cls(
            agent=agent,
            business=business,
            conversation=conversation,
            localization=localization,
            schema_version=schema_version,
            capabilities=capabilities,
            contact=contact,
            post_call_actions=post_call_actions,
            telephony=telephony,
        )

        return tenant_config_v5
