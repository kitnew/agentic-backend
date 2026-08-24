from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_identity_config import AgentIdentityConfig
    from ..models.business_config import BusinessConfig
    from ..models.contact_config import ContactConfig
    from ..models.conversation_config import ConversationConfig
    from ..models.handoff_config import HandoffConfig
    from ..models.localization_config import LocalizationConfig


T = TypeVar("T", bound="TenantConfigAuthoring")


@_attrs_define
class TenantConfigAuthoring:
    """
    Attributes:
        agent (AgentIdentityConfig):
        business (BusinessConfig):
        conversation (ConversationConfig):
        localization (LocalizationConfig):
        contact (ContactConfig | Unset):
        handoff (HandoffConfig | Unset):
    """

    agent: AgentIdentityConfig
    business: BusinessConfig
    conversation: ConversationConfig
    localization: LocalizationConfig
    contact: ContactConfig | Unset = UNSET
    handoff: HandoffConfig | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent.to_dict()

        business = self.business.to_dict()

        conversation = self.conversation.to_dict()

        localization = self.localization.to_dict()

        contact: dict[str, Any] | Unset = UNSET
        if not isinstance(self.contact, Unset):
            contact = self.contact.to_dict()

        handoff: dict[str, Any] | Unset = UNSET
        if not isinstance(self.handoff, Unset):
            handoff = self.handoff.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent": agent,
                "business": business,
                "conversation": conversation,
                "localization": localization,
            }
        )
        if contact is not UNSET:
            field_dict["contact"] = contact
        if handoff is not UNSET:
            field_dict["handoff"] = handoff

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_identity_config import AgentIdentityConfig
        from ..models.business_config import BusinessConfig
        from ..models.contact_config import ContactConfig
        from ..models.conversation_config import ConversationConfig
        from ..models.handoff_config import HandoffConfig
        from ..models.localization_config import LocalizationConfig

        d = dict(src_dict)
        agent = AgentIdentityConfig.from_dict(d.pop("agent"))

        business = BusinessConfig.from_dict(d.pop("business"))

        conversation = ConversationConfig.from_dict(d.pop("conversation"))

        localization = LocalizationConfig.from_dict(d.pop("localization"))

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

        tenant_config_authoring = cls(
            agent=agent,
            business=business,
            conversation=conversation,
            localization=localization,
            contact=contact,
            handoff=handoff,
        )

        return tenant_config_authoring
