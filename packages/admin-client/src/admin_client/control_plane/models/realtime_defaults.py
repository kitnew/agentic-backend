from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.realtime_input_transcription import RealtimeInputTranscription
    from ..models.realtime_interruption import RealtimeInterruption
    from ..models.realtime_semantic_vad import RealtimeSemanticVAD
    from ..models.realtime_server_vad import RealtimeServerVAD


T = TypeVar("T", bound="RealtimeDefaults")


@_attrs_define
class RealtimeDefaults:
    """
    Attributes:
        default_voice (str):  Default: 'marin'.
        deployment_ref (UUID):
        input_transcription (RealtimeInputTranscription):
        interruption (RealtimeInterruption):
        turn_completion (RealtimeSemanticVAD | RealtimeServerVAD):
    """

    deployment_ref: UUID
    input_transcription: RealtimeInputTranscription
    interruption: RealtimeInterruption
    turn_completion: RealtimeSemanticVAD | RealtimeServerVAD
    default_voice: str = "marin"

    def to_dict(self) -> dict[str, Any]:
        from ..models.realtime_server_vad import RealtimeServerVAD

        default_voice = self.default_voice

        deployment_ref = str(self.deployment_ref)

        input_transcription = self.input_transcription.to_dict()

        interruption = self.interruption.to_dict()

        turn_completion: dict[str, Any]
        if isinstance(self.turn_completion, RealtimeServerVAD):
            turn_completion = self.turn_completion.to_dict()
        else:
            turn_completion = self.turn_completion.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "default_voice": default_voice,
                "deployment_ref": deployment_ref,
                "input_transcription": input_transcription,
                "interruption": interruption,
                "turn_completion": turn_completion,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.realtime_input_transcription import RealtimeInputTranscription
        from ..models.realtime_interruption import RealtimeInterruption
        from ..models.realtime_semantic_vad import RealtimeSemanticVAD
        from ..models.realtime_server_vad import RealtimeServerVAD

        d = dict(src_dict)
        default_voice = d.pop("default_voice")

        deployment_ref = UUID(d.pop("deployment_ref"))

        input_transcription = RealtimeInputTranscription.from_dict(
            d.pop("input_transcription")
        )

        interruption = RealtimeInterruption.from_dict(d.pop("interruption"))

        def _parse_turn_completion(
            data: object,
        ) -> RealtimeSemanticVAD | RealtimeServerVAD:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                turn_completion_type_0 = RealtimeServerVAD.from_dict(data)

                return turn_completion_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            turn_completion_type_1 = RealtimeSemanticVAD.from_dict(data)

            return turn_completion_type_1

        turn_completion = _parse_turn_completion(d.pop("turn_completion"))

        realtime_defaults = cls(
            default_voice=default_voice,
            deployment_ref=deployment_ref,
            input_transcription=input_transcription,
            interruption=interruption,
            turn_completion=turn_completion,
        )

        return realtime_defaults
