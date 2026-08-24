from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.http_operation import HttpOperation
from contracts.tenant_components import (
    AgentIdentityConfig,
    BusinessConfig,
    ContactConfig,
    ConversationConfig,
    HandoffConfig,
    LocalizationConfig,
    PostCallActionInput,
    TenantAgentConfig,
    TenantKnowledgeConfig,
    TenantPromptConfig,
)
from contracts.voice_runtime import TenantRuntimeOverride


class _AuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TenantConfigAuthoring(_AuthoringModel):
    business: BusinessConfig
    contact: ContactConfig = Field(default_factory=ContactConfig)
    localization: LocalizationConfig
    agent: AgentIdentityConfig
    conversation: ConversationConfig
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)

    def to_component(self) -> TenantAgentConfig:
        return TenantAgentConfig.model_validate(self.model_dump(mode="json"))


class TenantRuntimeAuthoring(TenantRuntimeOverride):
    pass


class TenantPromptAuthoring(TenantPromptConfig):
    pass


class TenantKnowledgeAuthoring(_AuthoringModel):
    content: str = Field(default="", max_length=1_000_000)

    def to_component(self) -> TenantKnowledgeConfig:
        return TenantKnowledgeConfig(inline_context=self.content)


class TenantCapabilityAuthoring(_AuthoringModel):
    enabled: bool = True
    description: str = Field(min_length=1, max_length=1000)
    announcement: str | dict[str, str] = Field(min_length=1)
    agent_input_schema: dict[str, Any]
    bindings: dict[str, str] = Field(default_factory=dict)
    business_policy: dict[str, Any] = Field(default_factory=dict)
    execution: HttpOperation
    result_schema: dict[str, Any] | None = None


class TenantCapabilitiesAuthoring(_AuthoringModel):
    capabilities: dict[str, bool | TenantCapabilityAuthoring] = Field(default_factory=dict)


class TenantPostCallActionAuthoring(_AuthoringModel):
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    inputs: dict[str, PostCallActionInput] = Field(default_factory=dict, max_length=10)
    execution: HttpOperation


class TenantPostCallAuthoring(_AuthoringModel):
    actions: list[TenantPostCallActionAuthoring] = Field(default_factory=list, max_length=20)


class PlatformRuntimeAuthoring(_AuthoringModel):
    runtime_policy: dict[str, Any]


class SystemPromptAuthoring(_AuthoringModel):
    text: str = Field(default="", max_length=1_000_000)


class ProfilePromptAuthoring(_AuthoringModel):
    profile: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=1_000_000)


class AuthoringDraftMetadata(_AuthoringModel):
    id: UUID
    version: int
    updated_at: datetime
    comment: str | None = None


class AuthoringPublishedMetadata(_AuthoringModel):
    revision_id: UUID
    revision_number: int
    published_at: datetime


class AuthoringState(_AuthoringModel):
    value: Any | None = None
    published_value: Any | None = None
    source: Literal["draft", "published", "empty"]
    etag: str | None = None
    draft: AuthoringDraftMetadata | None = None
    published: AuthoringPublishedMetadata | None = None


class AuthoringChange(_AuthoringModel):
    path: str
    operation: Literal["add", "remove", "replace"]
    before: Any | None = None
    after: Any | None = None


class AuthoringIssue(_AuthoringModel):
    code: str
    path: str = ""
    message: str


class AuthoringImpact(_AuthoringModel):
    affected_components: list[str] = Field(default_factory=list)
    new_release_required: bool = False
    runtime_bundle_changes: bool = False
    telephony_reconciliation_required: bool = False


class AuthoringPlan(_AuthoringModel):
    valid: bool
    changes: list[AuthoringChange] = Field(default_factory=list)
    warnings: list[AuthoringIssue] = Field(default_factory=list)
    errors: list[AuthoringIssue] = Field(default_factory=list)
    impact: AuthoringImpact = Field(default_factory=AuthoringImpact)
