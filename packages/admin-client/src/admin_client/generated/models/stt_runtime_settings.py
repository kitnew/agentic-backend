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

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.interim_preflight_runtime_settings import (
        InterimPreflightRuntimeSettings,
    )
    from ..models.server_vad_runtime_settings import ServerVADRuntimeSettings


T = TypeVar("T", bound="STTRuntimeSettings")


@_attrs_define
class STTRuntimeSettings:
    """
    Attributes:
        model (str):
        provider (Literal['elevenlabs']):
        server_vad (ServerVADRuntimeSettings):
        interim_preflight (InterimPreflightRuntimeSettings | Unset):
    """

    model: str
    provider: Literal["elevenlabs"]
    server_vad: ServerVADRuntimeSettings
    interim_preflight: InterimPreflightRuntimeSettings | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        provider = self.provider

        server_vad = self.server_vad.to_dict()

        interim_preflight: dict[str, Any] | Unset = UNSET
        if not isinstance(self.interim_preflight, Unset):
            interim_preflight = self.interim_preflight.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
                "provider": provider,
                "server_vad": server_vad,
            }
        )
        if interim_preflight is not UNSET:
            field_dict["interim_preflight"] = interim_preflight

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.interim_preflight_runtime_settings import (
            InterimPreflightRuntimeSettings,
        )
        from ..models.server_vad_runtime_settings import ServerVADRuntimeSettings

        d = dict(src_dict)
        model = d.pop("model")

        provider = cast(Literal["elevenlabs"], d.pop("provider"))
        if provider != "elevenlabs":
            raise ValueError(
                f"provider must match const 'elevenlabs', got '{provider}'"
            )

        server_vad = ServerVADRuntimeSettings.from_dict(d.pop("server_vad"))

        _interim_preflight = d.pop("interim_preflight", UNSET)
        interim_preflight: InterimPreflightRuntimeSettings | Unset
        if isinstance(_interim_preflight, Unset):
            interim_preflight = UNSET
        else:
            interim_preflight = InterimPreflightRuntimeSettings.from_dict(
                _interim_preflight
            )

        stt_runtime_settings = cls(
            model=model,
            provider=provider,
            server_vad=server_vad,
            interim_preflight=interim_preflight,
        )

        return stt_runtime_settings
