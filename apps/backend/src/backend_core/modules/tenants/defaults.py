import json
from uuid import uuid4

from contracts.tenant_components import (
    AgentIdentityConfig,
    BusinessConfig,
    ConversationConfig,
    ConversationScope,
    LocalizationConfig,
    TenantAgentConfig,
    TenantCapabilitiesConfig,
    TenantKnowledgeConfig,
    TenantPostCallConfig,
    TenantPromptConfig,
    TenantTelephonyConfig,
)
from contracts.voice_runtime import TenantRuntimeOverride
from sqlalchemy import text

from backend_core.modules.tenants.release_repository import TenantComponent

_DRAFT_TABLES = {
    TenantComponent.AGENT: "tenant_agent_drafts",
    TenantComponent.RUNTIME: "tenant_runtime_drafts",
    TenantComponent.PROMPT: "tenant_prompt_component_drafts",
    TenantComponent.KNOWLEDGE: "tenant_knowledge_drafts",
    TenantComponent.CAPABILITIES: "tenant_capabilities_drafts",
    TenantComponent.POST_CALL: "tenant_post_call_drafts",
    TenantComponent.TELEPHONY: "tenant_telephony_drafts",
}
_REVISION_TABLES = {
    TenantComponent.AGENT: "tenant_agent_revisions",
    TenantComponent.RUNTIME: "tenant_runtime_component_revisions",
    TenantComponent.PROMPT: "tenant_prompt_component_revisions",
    TenantComponent.KNOWLEDGE: "tenant_knowledge_component_revisions",
    TenantComponent.CAPABILITIES: "tenant_capabilities_revisions",
    TenantComponent.POST_CALL: "tenant_post_call_revisions",
    TenantComponent.TELEPHONY: "tenant_telephony_revisions",
}


def default_component_payloads(
    display_name: str, business_type: str
) -> dict[TenantComponent, dict[str, object]]:
    values = {
        TenantComponent.AGENT: TenantAgentConfig(
            agent=AgentIdentityConfig(
                display_name=display_name,
                greeting="Hello, how can I help you?",
                profile="default",
            ),
            business=BusinessConfig(name=display_name, type=business_type),
            localization=LocalizationConfig(default_locale="en-US", timezone="UTC"),
            conversation=ConversationConfig(scope=ConversationScope.PROPERTY_ONLY),
        ),
        TenantComponent.RUNTIME: TenantRuntimeOverride(),
        TenantComponent.PROMPT: TenantPromptConfig(),
        TenantComponent.KNOWLEDGE: TenantKnowledgeConfig(),
        TenantComponent.CAPABILITIES: TenantCapabilitiesConfig(),
        TenantComponent.POST_CALL: TenantPostCallConfig(),
        TenantComponent.TELEPHONY: TenantTelephonyConfig(),
    }
    return {
        component: value.model_dump(mode="json")
        for component, value in values.items()
    }


def backfill_missing_component_drafts(connection) -> None:
    tenants = connection.execute(
        text("SELECT id, display_name, business_type FROM tenants")
    ).mappings()
    for tenant in tenants:
        defaults = default_component_payloads(
            tenant["display_name"], tenant["business_type"]
        )
        for component, payload in defaults.items():
            draft_table = _DRAFT_TABLES[component]
            revision_table = _REVISION_TABLES[component]
            if connection.execute(
                text(
                    f"SELECT 1 FROM {draft_table} "
                    "WHERE tenant_id = :tenant_id LIMIT 1"
                ),
                {"tenant_id": tenant["id"]},
            ).first():
                continue
            if connection.execute(
                text(
                    f"SELECT 1 FROM {revision_table} "
                    "WHERE tenant_id = :tenant_id LIMIT 1"
                ),
                {"tenant_id": tenant["id"]},
            ).first():
                continue
            connection.execute(
                text(
                    f"INSERT INTO {draft_table} "
                    "(id, tenant_id, payload, version) "
                    "VALUES (:id, :tenant_id, CAST(:payload AS jsonb), 1)"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant["id"],
                    "payload": json.dumps(payload),
                },
            )
