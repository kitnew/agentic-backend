from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.http_operation import HttpOperation
    from ..models.tenant_post_call_action_authoring_inputs import (
        TenantPostCallActionAuthoringInputs,
    )


T = TypeVar("T", bound="TenantPostCallActionAuthoring")


@_attrs_define
class TenantPostCallActionAuthoring:
    """
    Attributes:
        action_id (str):
        execution (HttpOperation):
        inputs (TenantPostCallActionAuthoringInputs | Unset):
    """

    action_id: str
    execution: HttpOperation
    inputs: TenantPostCallActionAuthoringInputs | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        action_id = self.action_id

        execution = self.execution.to_dict()

        inputs: dict[str, Any] | Unset = UNSET
        if not isinstance(self.inputs, Unset):
            inputs = self.inputs.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "action_id": action_id,
                "execution": execution,
            }
        )
        if inputs is not UNSET:
            field_dict["inputs"] = inputs

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.http_operation import HttpOperation
        from ..models.tenant_post_call_action_authoring_inputs import (
            TenantPostCallActionAuthoringInputs,
        )

        d = dict(src_dict)
        action_id = d.pop("action_id")

        execution = HttpOperation.from_dict(d.pop("execution"))

        _inputs = d.pop("inputs", UNSET)
        inputs: TenantPostCallActionAuthoringInputs | Unset
        if isinstance(_inputs, Unset):
            inputs = UNSET
        else:
            inputs = TenantPostCallActionAuthoringInputs.from_dict(_inputs)

        tenant_post_call_action_authoring = cls(
            action_id=action_id,
            execution=execution,
            inputs=inputs,
        )

        return tenant_post_call_action_authoring
