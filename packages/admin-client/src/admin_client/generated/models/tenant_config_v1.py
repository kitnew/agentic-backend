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
    from ..models.agent_config import AgentConfig
    from ..models.conversation_config import ConversationConfig
    from ..models.localization_config import LocalizationConfig
    from ..models.tenant_config_v1_capabilities import TenantConfigV1Capabilities


T = TypeVar("T", bound="TenantConfigV1")


@_attrs_define
class TenantConfigV1:
    """
    Attributes:
        agent (AgentConfig):
        conversation (ConversationConfig):
        localization (LocalizationConfig):
        schema_version (Literal[1]):
        capabilities (TenantConfigV1Capabilities | Unset):
    """

    agent: AgentConfig
    conversation: ConversationConfig
    localization: LocalizationConfig
    schema_version: Literal[1]
    capabilities: TenantConfigV1Capabilities | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent.to_dict()

        conversation = self.conversation.to_dict()

        localization = self.localization.to_dict()

        schema_version = self.schema_version

        capabilities: dict[str, Any] | Unset = UNSET
        if not isinstance(self.capabilities, Unset):
            capabilities = self.capabilities.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent": agent,
                "conversation": conversation,
                "localization": localization,
                "schema_version": schema_version,
            }
        )
        if capabilities is not UNSET:
            field_dict["capabilities"] = capabilities

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_config import AgentConfig
        from ..models.conversation_config import ConversationConfig
        from ..models.localization_config import LocalizationConfig
        from ..models.tenant_config_v1_capabilities import TenantConfigV1Capabilities

        d = dict(src_dict)
        agent = AgentConfig.from_dict(d.pop("agent"))

        conversation = ConversationConfig.from_dict(d.pop("conversation"))

        localization = LocalizationConfig.from_dict(d.pop("localization"))

        schema_version = cast(Literal[1], d.pop("schema_version"))
        if schema_version != 1:
            raise ValueError(
                f"schema_version must match const 1, got '{schema_version}'"
            )

        _capabilities = d.pop("capabilities", UNSET)
        capabilities: TenantConfigV1Capabilities | Unset
        if isinstance(_capabilities, Unset):
            capabilities = UNSET
        else:
            capabilities = TenantConfigV1Capabilities.from_dict(_capabilities)

        tenant_config_v1 = cls(
            agent=agent,
            conversation=conversation,
            localization=localization,
            schema_version=schema_version,
            capabilities=capabilities,
        )

        return tenant_config_v1
