from enum import Enum


class DeploymentKind(str, Enum):
    LLM = "llm"
    REALTIME = "realtime"
    STT = "stt"
    TTS = "tts"

    def __str__(self) -> str:
        return str(self.value)
