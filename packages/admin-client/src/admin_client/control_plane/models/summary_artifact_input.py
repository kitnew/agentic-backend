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

T = TypeVar("T", bound="SummaryArtifactInput")


@_attrs_define
class SummaryArtifactInput:
    """
    Attributes:
        artifact (Literal['call_summary']):
        representation (Literal['plain_text']):
    """

    artifact: Literal["call_summary"]
    representation: Literal["plain_text"]

    def to_dict(self) -> dict[str, Any]:
        artifact = self.artifact

        representation = self.representation

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
        artifact = cast(Literal["call_summary"], d.pop("artifact"))
        if artifact != "call_summary":
            raise ValueError(
                f"artifact must match const 'call_summary', got '{artifact}'"
            )

        representation = cast(Literal["plain_text"], d.pop("representation"))
        if representation != "plain_text":
            raise ValueError(
                f"representation must match const 'plain_text', got '{representation}'"
            )

        summary_artifact_input = cls(
            artifact=artifact,
            representation=representation,
        )

        return summary_artifact_input
