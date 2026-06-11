from pydantic import BaseModel, Field


class AgentProfile(BaseModel):
    profile_id: str
    name: str
    supported_intents: list[str]
    default_language: str
    tone: str
    behavior_rules: list[str] = Field(default_factory=list)
