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

from ..models.transcript_artifact_input_representation import (
    TranscriptArtifactInputRepresentation,
)

T = TypeVar("T", bound="TranscriptArtifactInput")


@_attrs_define
class TranscriptArtifactInput:
    """
    Attributes:
        artifact (Literal['transcript']):
        representation (TranscriptArtifactInputRepresentation):
    """

    artifact: Literal["transcript"]
    representation: TranscriptArtifactInputRepresentation

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
        artifact = cast(Literal["transcript"], d.pop("artifact"))
        if artifact != "transcript":
            raise ValueError(
                f"artifact must match const 'transcript', got '{artifact}'"
            )

        representation = TranscriptArtifactInputRepresentation(d.pop("representation"))

        transcript_artifact_input = cls(
            artifact=artifact,
            representation=representation,
        )

        return transcript_artifact_input
