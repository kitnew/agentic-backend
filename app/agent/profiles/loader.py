from pathlib import Path

import yaml
from pydantic import ValidationError

from app.agent.profiles.schemas import AgentProfile


class AgentProfileNotFoundError(Exception):
    pass


class AgentProfileInvalidError(Exception):
    pass


class AgentProfileLoader:
    def __init__(self, configs_dir: Path | None = None):
        self.configs_dir = configs_dir or Path(__file__).parent / "configs"

    def load(self, profile_id: str) -> AgentProfile:
        config_path = self.configs_dir / f"{profile_id}.yaml"
        if not config_path.exists():
            raise AgentProfileNotFoundError(f"Agent profile not found: {profile_id}")

        with config_path.open("r", encoding="utf-8") as config_file:
            raw_config = yaml.safe_load(config_file) or {}

        try:
            profile = AgentProfile.model_validate(raw_config)
        except ValidationError as exc:
            raise AgentProfileInvalidError(f"Agent profile is invalid: {profile_id}") from exc

        if profile.profile_id != profile_id:
            raise AgentProfileInvalidError(
                f"Agent profile id mismatch: expected {profile_id}, got {profile.profile_id}"
            )

        return profile

    def validate_all(self) -> list[AgentProfile]:
        profiles = []
        for config_path in sorted(self.configs_dir.glob("*.yaml")):
            profiles.append(self.load(config_path.stem))

        return profiles
