from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from contracts.tenant_components import ConversationScope
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentKind,
    ComponentRegistry,
    ScopeType,
)


class TenantAgentValue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=100)
    agent_profile: str = Field(
        min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"
    )
    greeting: str = Field(min_length=1, max_length=1000)
    conversation_scope: ConversationScope
    locale: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise PydanticCustomError(
                "invalid_timezone", "Unknown IANA timezone"
            ) from error
        return value


def register_agent_components(registry: object) -> None:
    assert isinstance(registry, ComponentRegistry)
    registry.register(
        ComponentDefinition(
            ComponentKind("agent.tenant"),
            TenantAgentValue,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
