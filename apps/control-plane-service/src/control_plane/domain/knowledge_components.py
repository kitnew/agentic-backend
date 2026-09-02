from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentKind,
    ComponentRegistry,
    ScopeType,
)


class TenantKnowledgeValue(BaseModel):
    """Inline tenant knowledge; retrieval artifacts are deliberately outside CP."""

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Strict(), Field(max_length=1_000_000)]

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, content: str) -> str:
        if not content.strip():
            raise ValueError("content must not be blank")
        return content


def register_knowledge_components(registry: object) -> None:
    assert isinstance(registry, ComponentRegistry)
    registry.register(
        ComponentDefinition(
            ComponentKind("knowledge.tenant"),
            TenantKnowledgeValue,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
