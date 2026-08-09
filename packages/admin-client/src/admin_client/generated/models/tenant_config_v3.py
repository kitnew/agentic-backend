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
    from ..models.tenant_config_v3_capabilities import TenantConfigV3Capabilities


T = TypeVar("T", bound="TenantConfigV3")


@_attrs_define
class TenantConfigV3:
    """
    Attributes:
        agent (AgentConfigV3):
        business (BusinessConfig):
        conversation (ConversationConfig):
        localization (LocalizationConfig):
        schema_version (Literal[3]):
        capabilities (TenantConfigV3Capabilities | Unset):
        contact (ContactConfig | Unset):
    """

    agent: AgentConfigV3
    business: BusinessConfig
    conversation: ConversationConfig
    localization: LocalizationConfig
    schema_version: Literal[3]
    capabilities: TenantConfigV3Capabilities | Unset = UNSET
    contact: ContactConfig | Unset = UNSET

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

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_config_v3 import AgentConfigV3
        from ..models.business_config import BusinessConfig
        from ..models.contact_config import ContactConfig
        from ..models.conversation_config import ConversationConfig
        from ..models.localization_config import LocalizationConfig
        from ..models.tenant_config_v3_capabilities import TenantConfigV3Capabilities

        d = dict(src_dict)
        agent = AgentConfigV3.from_dict(d.pop("agent"))

        business = BusinessConfig.from_dict(d.pop("business"))

        conversation = ConversationConfig.from_dict(d.pop("conversation"))

        localization = LocalizationConfig.from_dict(d.pop("localization"))

        schema_version = cast(Literal[3], d.pop("schema_version"))
        if schema_version != 3:
            raise ValueError(
                f"schema_version must match const 3, got '{schema_version}'"
            )

        _capabilities = d.pop("capabilities", UNSET)
        capabilities: TenantConfigV3Capabilities | Unset
        if isinstance(_capabilities, Unset):
            capabilities = UNSET
        else:
            capabilities = TenantConfigV3Capabilities.from_dict(_capabilities)

        _contact = d.pop("contact", UNSET)
        contact: ContactConfig | Unset
        if isinstance(_contact, Unset):
            contact = UNSET
        else:
            contact = ContactConfig.from_dict(_contact)

        tenant_config_v3 = cls(
            agent=agent,
            business=business,
            conversation=conversation,
            localization=localization,
            schema_version=schema_version,
            capabilities=capabilities,
            contact=contact,
        )

        return tenant_config_v3
