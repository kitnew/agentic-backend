from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.post_call_action_input_artifact import PostCallActionInputArtifact
from ..models.post_call_action_input_representation import (
    PostCallActionInputRepresentation,
)

T = TypeVar("T", bound="PostCallActionInput")


@_attrs_define
class PostCallActionInput:
    """
    Attributes:
        artifact (PostCallActionInputArtifact):
        representation (PostCallActionInputRepresentation):
    """

    artifact: PostCallActionInputArtifact
    representation: PostCallActionInputRepresentation

    def to_dict(self) -> dict[str, Any]:
        artifact = self.artifact.value

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
        artifact = PostCallActionInputArtifact(d.pop("artifact"))

        representation = PostCallActionInputRepresentation(d.pop("representation"))

        post_call_action_input = cls(
            artifact=artifact,
            representation=representation,
        )

        return post_call_action_input
