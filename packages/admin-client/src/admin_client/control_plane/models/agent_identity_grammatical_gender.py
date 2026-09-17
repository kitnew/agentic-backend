from enum import Enum


class AgentIdentityGrammaticalGender(str, Enum):
    FEMININE = "feminine"
    MASCULINE = "masculine"
    NEUTRAL = "neutral"

    def __str__(self) -> str:
        return str(self.value)
