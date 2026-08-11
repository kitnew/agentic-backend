from enum import Enum


class PostCallActionInputArtifact(str, Enum):
    CALL_RECORDING = "call_recording"
    CALL_SUMMARY = "call_summary"
    TRANSCRIPT = "transcript"

    def __str__(self) -> str:
        return str(self.value)
