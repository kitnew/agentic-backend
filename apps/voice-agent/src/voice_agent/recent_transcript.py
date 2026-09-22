from collections import deque
from typing import Any, cast

from livekit import agents
from livekit.agents import llm
from livekit.agents.voice.events import UserInputTranscribedEvent


class RecentTranscriptBuffer:
    def __init__(self, max_segments: int = 20) -> None:
        self._segments: deque[tuple[int, str]] = deque(maxlen=max_segments)
        self._next_seq = 1

    def on_user_input_transcribed(self, event: UserInputTranscribedEvent) -> None:
        if not event.is_final or not event.transcript:
            return
        self._segments.append((self._next_seq, event.transcript))
        self._next_seq += 1

    def recent(self, turns: int) -> dict[str, object]:
        selected = list(self._segments)[-turns:]
        return {
            "segments": [{"seq": seq, "text": text} for seq, text in selected],
            "combined_text": " ".join(text for _, text in selected),
        }


def recent_transcript_tool(buffer: RecentTranscriptBuffer) -> llm.RawFunctionTool:
    async def invoke(
        context: agents.RunContext[Any],
        raw_arguments: dict[str, object],
    ) -> dict[str, object]:
        del context
        return buffer.recent(cast(int, raw_arguments["turns"]))

    return cast(
        llm.RawFunctionTool,
        agents.function_tool(
            raw_schema={
                "name": "get_recent_transcript",
                "description": (
                    "Read recent finalized caller transcript segments when exact wording "
                    "matters. Request multiple turns when a value was spoken in parts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "turns": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "Number of most recent segments to return",
                        }
                    },
                    "required": ["turns"],
                    "additionalProperties": False,
                },
            }
        )(invoke),
    )
