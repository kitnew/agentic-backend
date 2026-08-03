import json
from pathlib import Path

from app.agent.schemas.context import AgentContext


class PromptLoader:
    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = prompts_dir or Path(__file__).parent
        self.profiles_dir = self.prompts_dir / "profiles"

    def load_system_prompt(self) -> str:
        return self._read_prompt(self.prompts_dir / "system.md")

    def load_profile_prompt(self, profile_name: str | None) -> str:
        if not profile_name:
            raise Exception("Profile name is required")

        profile_path = self.profiles_dir / f"{profile_name}.md"
        if not profile_path.exists():
            raise Exception(f"Profile {profile_name} does not exist")

        return self._read_prompt(profile_path)

    def build_system_prompt(self, context: AgentContext) -> str:
        prompt_parts = [
            self._section("global_system_instructions", self.load_system_prompt()),
            self._section(
                "profile_instructions",
                self.load_profile_prompt(context.get("agent_profile")),
            ),
            self._section("tenant_instructions", self._build_tenant_instructions(context)),
            self._section("tenant_identity", self._dump(context.get("tenant_identity"))),
            self._section("tenant_business_context", self._build_business_context(context)),
            self._section("tenant_knowledge_base", context.get("knowledge_base", "")),
        ]

        return "\n\n".join(part for part in prompt_parts if part)

    def _section(self, name: str, content: str) -> str:
        if not content:
            return ""
        return f"<{name}>\n{content}\n</{name}>"

    def _build_business_context(self, context: AgentContext) -> str:
        parts = [
            self._build_temporal_context(context),
            self._build_conversation_scope(context),
            self._build_business_info(context),
            self._build_reservation_policy(context),
            self._build_required_reservation_fields(context),
            self._build_schedule_summary(context),
            self._build_supported_operations(context),
        ]
        return "\n\n".join(part for part in parts if part)

    def _build_temporal_context(self, context: AgentContext) -> str:
        return (
            "Current local tenant date and time for this turn:\n"
            f"current local datetime: {context.get('current_local_datetime', context['datetime'])}\n"
            f"current local date: {context.get('current_local_date', context['date'])}\n"
            f"current local time: {context.get('current_local_time', context['time'])}\n"
            f"locale: {context['locale']}\n"
            f"tenant timezone: {context['timezone']}"
        )

    def _build_conversation_scope(self, context: AgentContext) -> str:
        scope = context.get("conversation_scope")
        return f"Conversation scope:\n{scope}" if scope else ""

    def _build_agent_style_rules(self, context: AgentContext) -> str:
        style_rules = context.get("agent_style_rules") or []
        if not style_rules:
            return ""
        return "Agent style rules:\n" + "\n".join(f"- {rule}" for rule in style_rules)

    def _build_tenant_instructions(self, context: AgentContext) -> str:
        parts = [
            self._build_agent_style_rules(context),
            context.get("tenant_instructions", ""),
        ]
        return "\n\n".join(part for part in parts if part)

    def _build_business_info(self, context: AgentContext) -> str:
        business_info = context.get("business_info") or {}
        if not business_info:
            return ""
        return "Business information:\n" + self._dump(business_info)

    def _build_reservation_policy(self, context: AgentContext) -> str:
        reservation_policy = context.get("reservation_policy")
        if not reservation_policy:
            return ""
        return f"Reservation policy:\n{reservation_policy}"

    def _build_required_reservation_fields(self, context: AgentContext) -> str:
        required_fields = context.get("required_reservation_fields") or []
        if not required_fields:
            return ""
        return "Required reservation fields:\n" + "\n".join(
            f"- {field}" for field in required_fields
        )

    def _build_schedule_summary(self, context: AgentContext) -> str:
        schedule_summary = context.get("schedule_summary")
        if not schedule_summary:
            return ""
        return f"Reservation schedule:\n{schedule_summary}"

    def _build_supported_operations(self, context: AgentContext) -> str:
        operations = context.get("supported_operations")
        return f"Supported operations:\n{operations}" if operations else ""

    def _dump(self, value) -> str:
        if not value:
            return ""
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)

    def _read_prompt(self, path: Path) -> str:
        with path.open("r", encoding="utf-8") as prompt_file:
            return prompt_file.read().strip()


def load_system_prompt() -> str:
    return PromptLoader().load_system_prompt()
