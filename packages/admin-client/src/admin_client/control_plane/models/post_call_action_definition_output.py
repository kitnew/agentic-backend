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
    from ..models.http_semantic_execution_output import HttpSemanticExecutionOutput
    from ..models.post_call_action_definition_output_artifact_inputs import (
        PostCallActionDefinitionOutputArtifactInputs,
    )
    from ..models.post_call_action_definition_output_result_schema_type_0 import (
        PostCallActionDefinitionOutputResultSchemaType0,
    )


T = TypeVar("T", bound="PostCallActionDefinitionOutput")


@_attrs_define
class PostCallActionDefinitionOutput:
    """
    Attributes:
        artifact_inputs (PostCallActionDefinitionOutputArtifactInputs):
        execution (HttpSemanticExecutionOutput):
        phase (Literal['post_call']):
        result_schema (None | PostCallActionDefinitionOutputResultSchemaType0 | Unset):
    """

    artifact_inputs: PostCallActionDefinitionOutputArtifactInputs
    execution: HttpSemanticExecutionOutput
    phase: Literal["post_call"]
    result_schema: None | PostCallActionDefinitionOutputResultSchemaType0 | Unset = (
        UNSET
    )

    def to_dict(self) -> dict[str, Any]:
        from ..models.post_call_action_definition_output_result_schema_type_0 import (
            PostCallActionDefinitionOutputResultSchemaType0,
        )

        artifact_inputs = self.artifact_inputs.to_dict()

        execution = self.execution.to_dict()

        phase = self.phase

        result_schema: dict[str, Any] | None | Unset
        if isinstance(self.result_schema, Unset):
            result_schema = UNSET
        elif isinstance(
            self.result_schema, PostCallActionDefinitionOutputResultSchemaType0
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
        from ..models.http_semantic_execution_output import HttpSemanticExecutionOutput
        from ..models.post_call_action_definition_output_artifact_inputs import (
            PostCallActionDefinitionOutputArtifactInputs,
        )
        from ..models.post_call_action_definition_output_result_schema_type_0 import (
            PostCallActionDefinitionOutputResultSchemaType0,
        )

        d = dict(src_dict)
        artifact_inputs = PostCallActionDefinitionOutputArtifactInputs.from_dict(
            d.pop("artifact_inputs")
        )

        execution = HttpSemanticExecutionOutput.from_dict(d.pop("execution"))

        phase = cast(Literal["post_call"], d.pop("phase"))
        if phase != "post_call":
            raise ValueError(f"phase must match const 'post_call', got '{phase}'")

        def _parse_result_schema(
            data: object,
        ) -> None | PostCallActionDefinitionOutputResultSchemaType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_schema_type_0 = (
                    PostCallActionDefinitionOutputResultSchemaType0.from_dict(data)
                )

                return result_schema_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | PostCallActionDefinitionOutputResultSchemaType0 | Unset, data
            )

        result_schema = _parse_result_schema(d.pop("result_schema", UNSET))

        post_call_action_definition_output = cls(
            artifact_inputs=artifact_inputs,
            execution=execution,
            phase=phase,
            result_schema=result_schema,
        )

        return post_call_action_definition_output
