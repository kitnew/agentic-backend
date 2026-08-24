from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.post_call_artifact_descriptor_artifact import (
    PostCallArtifactDescriptorArtifact,
)

T = TypeVar("T", bound="PostCallArtifactDescriptor")


@_attrs_define
class PostCallArtifactDescriptor:
    """
    Attributes:
        artifact (PostCallArtifactDescriptorArtifact):
        description (str):
        representations (list[str]):
    """

    artifact: PostCallArtifactDescriptorArtifact
    description: str
    representations: list[str]

    def to_dict(self) -> dict[str, Any]:
        artifact = self.artifact.value

        description = self.description

        representations = self.representations

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "artifact": artifact,
                "description": description,
                "representations": representations,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        artifact = PostCallArtifactDescriptorArtifact(d.pop("artifact"))

        description = d.pop("description")

        representations = cast(list[str], d.pop("representations"))

        post_call_artifact_descriptor = cls(
            artifact=artifact,
            description=description,
            representations=representations,
        )

        return post_call_artifact_descriptor
