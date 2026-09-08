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
    from ..models.http_semantic_execution_input import HttpSemanticExecutionInput
    from ..models.post_call_action_definition_input_artifact_inputs import (
        PostCallActionDefinitionInputArtifactInputs,
    )
    from ..models.post_call_action_definition_input_result_schema_type_0 import (
        PostCallActionDefinitionInputResultSchemaType0,
    )


T = TypeVar("T", bound="PostCallActionDefinitionInput")


@_attrs_define
class PostCallActionDefinitionInput:
    """
    Attributes:
        artifact_inputs (PostCallActionDefinitionInputArtifactInputs):
        execution (HttpSemanticExecutionInput):
        phase (Literal['post_call']):
        result_schema (None | PostCallActionDefinitionInputResultSchemaType0 | Unset):
    """

    artifact_inputs: PostCallActionDefinitionInputArtifactInputs
    execution: HttpSemanticExecutionInput
    phase: Literal["post_call"]
    result_schema: None | PostCallActionDefinitionInputResultSchemaType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.post_call_action_definition_input_result_schema_type_0 import (
            PostCallActionDefinitionInputResultSchemaType0,
        )

        artifact_inputs = self.artifact_inputs.to_dict()

        execution = self.execution.to_dict()

        phase = self.phase

        result_schema: dict[str, Any] | None | Unset
        if isinstance(self.result_schema, Unset):
            result_schema = UNSET
        elif isinstance(
            self.result_schema, PostCallActionDefinitionInputResultSchemaType0
        ):
            result_schema = self.result_schema.to_dict()
        else:
            result_schema = self.result_schema

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "artifact_inputs": artifact_inputs,
                "execution": execution,
                "phase": phase,
            }
        )
        if result_schema is not UNSET:
            field_dict["result_schema"] = result_schema

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.http_semantic_execution_input import HttpSemanticExecutionInput
        from ..models.post_call_action_definition_input_artifact_inputs import (
            PostCallActionDefinitionInputArtifactInputs,
        )
        from ..models.post_call_action_definition_input_result_schema_type_0 import (
            PostCallActionDefinitionInputResultSchemaType0,
        )

        d = dict(src_dict)
        artifact_inputs = PostCallActionDefinitionInputArtifactInputs.from_dict(
            d.pop("artifact_inputs")
        )

        execution = HttpSemanticExecutionInput.from_dict(d.pop("execution"))

        phase = cast(Literal["post_call"], d.pop("phase"))
        if phase != "post_call":
            raise ValueError(f"phase must match const 'post_call', got '{phase}'")

        def _parse_result_schema(
            data: object,
        ) -> None | PostCallActionDefinitionInputResultSchemaType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_schema_type_0 = (
                    PostCallActionDefinitionInputResultSchemaType0.from_dict(data)
                )

                return result_schema_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | PostCallActionDefinitionInputResultSchemaType0 | Unset, data
            )

        result_schema = _parse_result_schema(d.pop("result_schema", UNSET))

        post_call_action_definition_input = cls(
            artifact_inputs=artifact_inputs,
            execution=execution,
            phase=phase,
            result_schema=result_schema,
        )

        return post_call_action_definition_input
