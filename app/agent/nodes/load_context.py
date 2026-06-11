from functools import lru_cache
from pathlib import Path

from app.agent.contracts.input import AgentInput
from app.agent.contracts.state import AgentWorkingState
from app.agent.profiles.loader import AgentProfileLoader
from app.agent.prompts.tenant_prompt_builder import build_tenant_prompt


SYSTEM_PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "system_prompt.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


class LoadContextNode:
    def __init__(self, profile_loader: AgentProfileLoader):
        self.profile_loader = profile_loader

    def __call__(self, agent_input: AgentInput) -> AgentWorkingState:
        tenant_agent = agent_input.tenant_context.agent
        profile = self.profile_loader.load(tenant_agent.profile)
        tenant_context = agent_input.tenant_context.model_dump(mode="json")
        profile_data = profile.model_dump(mode="json")
        system_prompt = load_system_prompt()
        tenant_prompt = build_tenant_prompt(tenant_context, profile_data)
        return AgentWorkingState(
            tenant_id=agent_input.tenant_id,
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            channel=agent_input.channel,
            message_text=agent_input.message_text,
            tenant_context=tenant_context,
            tenant_agent=tenant_agent.model_dump(mode="json"),
            profile=profile_data,
            chat_history=agent_input.chat_history,
            system_prompt=system_prompt,
            tenant_prompt=tenant_prompt,
            trace={
                "load_context": {
                    "system_prompt_loaded": bool(system_prompt),
                    "tenant_prompt_loaded": bool(tenant_prompt),
                    "profile_id": profile.profile_id,
                }
            },
        )
