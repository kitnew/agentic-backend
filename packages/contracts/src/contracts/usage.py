"""Cumulative, per-model call usage reported by the voice agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CallModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=128)
    service: Literal["llm", "stt", "tts"]
    model: str = Field(min_length=1, max_length=255)
    source: Literal["livekit_session_1_8_2"] = "livekit_session_1_8_2"
    observed_at: datetime
    counters: dict[str, int | float] = Field(min_length=1)


class CallUsageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage: list[CallModelUsage] = Field(max_length=100)
