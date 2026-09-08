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
    from ..models.date_range_constraint import DateRangeConstraint
    from ..models.http_semantic_execution_output import HttpSemanticExecutionOutput
    from ..models.runtime_action_definition_output_agent_input_schema import (
        RuntimeActionDefinitionOutputAgentInputSchema,
    )
    from ..models.runtime_action_definition_output_announcement_type_1 import (
        RuntimeActionDefinitionOutputAnnouncementType1,
    )
    from ..models.runtime_action_definition_output_bindings import (
        RuntimeActionDefinitionOutputBindings,
    )
    from ..models.runtime_action_definition_output_result_schema_type_0 import (
        RuntimeActionDefinitionOutputResultSchemaType0,
    )
    from ..models.runtime_business_policy import RuntimeBusinessPolicy


T = TypeVar("T", bound="RuntimeActionDefinitionOutput")


@_attrs_define
class RuntimeActionDefinitionOutput:
    """
    Attributes:
        agent_input_schema (RuntimeActionDefinitionOutputAgentInputSchema):
        announcement (RuntimeActionDefinitionOutputAnnouncementType1 | str):
        description (str):
        execution (HttpSemanticExecutionOutput):
        phase (Literal['runtime']):
        bindings (RuntimeActionDefinitionOutputBindings | Unset):
        business_policy (RuntimeBusinessPolicy | Unset):
        input_constraints (list[DateRangeConstraint] | Unset):
        result_schema (None | RuntimeActionDefinitionOutputResultSchemaType0 | Unset):
    """

    agent_input_schema: RuntimeActionDefinitionOutputAgentInputSchema
    announcement: RuntimeActionDefinitionOutputAnnouncementType1 | str
    description: str
    execution: HttpSemanticExecutionOutput
    phase: Literal["runtime"]
    bindings: RuntimeActionDefinitionOutputBindings | Unset = UNSET
    business_policy: RuntimeBusinessPolicy | Unset = UNSET
    input_constraints: list[DateRangeConstraint] | Unset = UNSET
    result_schema: None | RuntimeActionDefinitionOutputResultSchemaType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.runtime_action_definition_output_announcement_type_1 import (
            RuntimeActionDefinitionOutputAnnouncementType1,
        )
        from ..models.runtime_action_definition_output_result_schema_type_0 import (
            RuntimeActionDefinitionOutputResultSchemaType0,
        )

        agent_input_schema = self.agent_input_schema.to_dict()

        announcement: dict[str, Any] | str
        if isinstance(
            self.announcement, RuntimeActionDefinitionOutputAnnouncementType1
        ):
            announcement = self.announcement.to_dict()
        else:
            announcement = self.announcement

        description = self.description

        execution = self.execution.to_dict()

        phase = self.phase

        bindings: dict[str, Any] | Unset = UNSET
        if not isinstance(self.bindings, Unset):
            bindings = self.bindings.to_dict()

        business_policy: dict[str, Any] | Unset = UNSET
        if not isinstance(self.business_policy, Unset):
            business_policy = self.business_policy.to_dict()

        input_constraints: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.input_constraints, Unset):
            input_constraints = []
            for input_constraints_item_data in self.input_constraints:
                input_constraints_item = input_constraints_item_data.to_dict()
                input_constraints.append(input_constraints_item)

        result_schema: dict[str, Any] | None | Unset
        if isinstance(self.result_schema, Unset):
            result_schema = UNSET
        elif isinstance(
            self.result_schema, RuntimeActionDefinitionOutputResultSchemaType0
        ):
            result_schema = self.result_schema.to_dict()
        else:
            result_schema = self.result_schema

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent_input_schema": agent_input_schema,
                "announcement": announcement,
                "description": description,
                "execution": execution,
                "phase": phase,
            }
        )
        if bindings is not UNSET:
            field_dict["bindings"] = bindings
        if business_policy is not UNSET:
            field_dict["business_policy"] = business_policy
        if input_constraints is not UNSET:
            field_dict["input_constraints"] = input_constraints
        if result_schema is not UNSET:
            field_dict["result_schema"] = result_schema

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.date_range_constraint import DateRangeConstraint
        from ..models.http_semantic_execution_output import HttpSemanticExecutionOutput
        from ..models.runtime_action_definition_output_agent_input_schema import (
            RuntimeActionDefinitionOutputAgentInputSchema,
        )
        from ..models.runtime_action_definition_output_announcement_type_1 import (
            RuntimeActionDefinitionOutputAnnouncementType1,
        )
        from ..models.runtime_action_definition_output_bindings import (
            RuntimeActionDefinitionOutputBindings,
        )
        from ..models.runtime_action_definition_output_result_schema_type_0 import (
            RuntimeActionDefinitionOutputResultSchemaType0,
        )
        from ..models.runtime_business_policy import RuntimeBusinessPolicy

        d = dict(src_dict)
        agent_input_schema = RuntimeActionDefinitionOutputAgentInputSchema.from_dict(
            d.pop("agent_input_schema")
        )

        def _parse_announcement(
            data: object,
        ) -> RuntimeActionDefinitionOutputAnnouncementType1 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                announcement_type_1 = (
                    RuntimeActionDefinitionOutputAnnouncementType1.from_dict(data)
                )

                return announcement_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(RuntimeActionDefinitionOutputAnnouncementType1 | str, data)

        announcement = _parse_announcement(d.pop("announcement"))

        description = d.pop("description")

        execution = HttpSemanticExecutionOutput.from_dict(d.pop("execution"))

        phase = cast(Literal["runtime"], d.pop("phase"))
        if phase != "runtime":
            raise ValueError(f"phase must match const 'runtime', got '{phase}'")

        _bindings = d.pop("bindings", UNSET)
        bindings: RuntimeActionDefinitionOutputBindings | Unset
        if isinstance(_bindings, Unset):
            bindings = UNSET
        else:
            bindings = RuntimeActionDefinitionOutputBindings.from_dict(_bindings)

        _business_policy = d.pop("business_policy", UNSET)
        business_policy: RuntimeBusinessPolicy | Unset
        if isinstance(_business_policy, Unset):
            business_policy = UNSET
        else:
            business_policy = RuntimeBusinessPolicy.from_dict(_business_policy)

        _input_constraints = d.pop("input_constraints", UNSET)
        input_constraints: list[DateRangeConstraint] | Unset = UNSET
        if _input_constraints is not UNSET:
            input_constraints = []
            for input_constraints_item_data in _input_constraints:
                input_constraints_item = DateRangeConstraint.from_dict(
                    input_constraints_item_data
                )

                input_constraints.append(input_constraints_item)

        def _parse_result_schema(
            data: object,
        ) -> None | RuntimeActionDefinitionOutputResultSchemaType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_schema_type_0 = (
                    RuntimeActionDefinitionOutputResultSchemaType0.from_dict(data)
                )

                return result_schema_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | RuntimeActionDefinitionOutputResultSchemaType0 | Unset, data
            )

        result_schema = _parse_result_schema(d.pop("result_schema", UNSET))

        runtime_action_definition_output = cls(
            agent_input_schema=agent_input_schema,
            announcement=announcement,
            description=description,
            execution=execution,
            phase=phase,
            bindings=bindings,
            business_policy=business_policy,
            input_constraints=input_constraints,
            result_schema=result_schema,
        )

        return runtime_action_definition_output
