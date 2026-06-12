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
            self.load_system_prompt(),
            self.load_profile_prompt(context.get("agent_profile")),
            self._build_temporal_context(context),
        ]

        tenant_prompt = context.get("tenant_prompt")
        if tenant_prompt:
            prompt_parts.append(f"Tenant instructions:\n{tenant_prompt}")

        business_profile = context.get("business_profile")
        if business_profile:
            prompt_parts.append(f"Business profile:\n{business_profile}")

        available_capabilities = context.get("available_capabilities") or []
        if available_capabilities:
            prompt_parts.append(
                "Available capabilities:\n"
                + "\n".join(f"- {name}" for name in available_capabilities)
            )

        return "\n\n".join(part for part in prompt_parts if part)

    def _build_temporal_context(self, context: AgentContext) -> str:
        return (
            "Current tenant time:\n"
            f"now: {context['now']}\n"
            f"datetime: {context['datetime']}\n"
            f"locale: {context['locale']}\n"
            f"date: {context['date']}\n"
            f"time: {context['time']}\n"
            f"timezone: {context['timezone']}"
        )

    def _read_prompt(self, path: Path) -> str:
        with path.open("r", encoding="utf-8") as prompt_file:
            return prompt_file.read().strip()


def load_system_prompt() -> str:
    return PromptLoader().load_system_prompt()
