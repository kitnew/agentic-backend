from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.recording_artifact_input_representation import (
    RecordingArtifactInputRepresentation,
)

T = TypeVar("T", bound="RecordingArtifactInput")


@_attrs_define
class RecordingArtifactInput:
    """
    Attributes:
        artifact (Literal['call_recording']):
        representation (RecordingArtifactInputRepresentation):
    """

    artifact: Literal["call_recording"]
    representation: RecordingArtifactInputRepresentation

    def to_dict(self) -> dict[str, Any]:
        artifact = self.artifact

        representation = self.representation.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "artifact": artifact,
                "representation": representation,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        artifact = cast(Literal["call_recording"], d.pop("artifact"))
        if artifact != "call_recording":
            raise ValueError(
                f"artifact must match const 'call_recording', got '{artifact}'"
            )

        representation = RecordingArtifactInputRepresentation(d.pop("representation"))

        recording_artifact_input = cls(
            artifact=artifact,
            representation=representation,
        )

        return recording_artifact_input
