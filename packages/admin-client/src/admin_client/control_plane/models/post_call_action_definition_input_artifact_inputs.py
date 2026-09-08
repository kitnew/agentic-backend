from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.recording_artifact_input import RecordingArtifactInput
    from ..models.summary_artifact_input import SummaryArtifactInput
    from ..models.transcript_artifact_input import TranscriptArtifactInput


T = TypeVar("T", bound="PostCallActionDefinitionInputArtifactInputs")


@_attrs_define
class PostCallActionDefinitionInputArtifactInputs:
    """ """

    additional_properties: dict[
        str, RecordingArtifactInput | SummaryArtifactInput | TranscriptArtifactInput
    ] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.recording_artifact_input import RecordingArtifactInput
        from ..models.transcript_artifact_input import TranscriptArtifactInput

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            if isinstance(prop, TranscriptArtifactInput) or isinstance(
                prop, RecordingArtifactInput
            ):
                field_dict[prop_name] = prop.to_dict()
            else:
                field_dict[prop_name] = prop.to_dict()

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.recording_artifact_input import RecordingArtifactInput
        from ..models.summary_artifact_input import SummaryArtifactInput
        from ..models.transcript_artifact_input import TranscriptArtifactInput

        d = dict(src_dict)
        post_call_action_definition_input_artifact_inputs = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():

            def _parse_additional_property(
                data: object,
            ) -> (
                RecordingArtifactInput | SummaryArtifactInput | TranscriptArtifactInput
            ):
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    additional_property_type_0 = TranscriptArtifactInput.from_dict(data)

                    return additional_property_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    additional_property_type_1 = RecordingArtifactInput.from_dict(data)

                    return additional_property_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                additional_property_type_2 = SummaryArtifactInput.from_dict(data)

                return additional_property_type_2

            additional_property = _parse_additional_property(prop_dict)

            additional_properties[prop_name] = additional_property

        post_call_action_definition_input_artifact_inputs.additional_properties = (
            additional_properties
        )
        return post_call_action_definition_input_artifact_inputs

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(
        self, key: str
    ) -> RecordingArtifactInput | SummaryArtifactInput | TranscriptArtifactInput:
        return self.additional_properties[key]

    def __setitem__(
        self,
        key: str,
        value: RecordingArtifactInput | SummaryArtifactInput | TranscriptArtifactInput,
    ) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
