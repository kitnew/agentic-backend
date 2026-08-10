from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.server_vad_runtime_settings import ServerVADRuntimeSettings


T = TypeVar("T", bound="STTRuntimeSettings")


@_attrs_define
class STTRuntimeSettings:
    """
    Attributes:
        model (str):
        provider (Literal['elevenlabs']):
        server_vad (ServerVADRuntimeSettings):
    """

    model: str
    provider: Literal["elevenlabs"]
    server_vad: ServerVADRuntimeSettings

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        provider = self.provider

        server_vad = self.server_vad.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
                "provider": provider,
                "server_vad": server_vad,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.server_vad_runtime_settings import ServerVADRuntimeSettings

        d = dict(src_dict)
        model = d.pop("model")

        provider = cast(Literal["elevenlabs"], d.pop("provider"))
        if provider != "elevenlabs":
            raise ValueError(
                f"provider must match const 'elevenlabs', got '{provider}'"
            )

        server_vad = ServerVADRuntimeSettings.from_dict(d.pop("server_vad"))

        stt_runtime_settings = cls(
            model=model,
            provider=provider,
            server_vad=server_vad,
        )

        return stt_runtime_settings
