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
    from ..models.managed_webhook_execution import ManagedWebhookExecution
    from ..models.post_call_action_inputs import PostCallActionInputs


T = TypeVar("T", bound="PostCallAction")


@_attrs_define
class PostCallAction:
    """
    Attributes:
        action_id (str):
        execution (ManagedWebhookExecution):
        semantic_key (str):
        semantic_version (int):
        inputs (PostCallActionInputs | Unset):
        type_ (Literal['http.post_json'] | Unset):  Default: 'http.post_json'.
    """

    action_id: str
    execution: ManagedWebhookExecution
    semantic_key: str
    semantic_version: int
    inputs: PostCallActionInputs | Unset = UNSET
    type_: Literal["http.post_json"] | Unset = "http.post_json"

    def to_dict(self) -> dict[str, Any]:
        action_id = self.action_id

        execution = self.execution.to_dict()

        semantic_key = self.semantic_key

        semantic_version = self.semantic_version

        inputs: dict[str, Any] | Unset = UNSET
        if not isinstance(self.inputs, Unset):
            inputs = self.inputs.to_dict()

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "action_id": action_id,
                "execution": execution,
                "semantic_key": semantic_key,
                "semantic_version": semantic_version,
            }
        )
        if inputs is not UNSET:
            field_dict["inputs"] = inputs
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.managed_webhook_execution import ManagedWebhookExecution
        from ..models.post_call_action_inputs import PostCallActionInputs

        d = dict(src_dict)
        action_id = d.pop("action_id")

        execution = ManagedWebhookExecution.from_dict(d.pop("execution"))

        semantic_key = d.pop("semantic_key")

        semantic_version = d.pop("semantic_version")

        _inputs = d.pop("inputs", UNSET)
        inputs: PostCallActionInputs | Unset
        if isinstance(_inputs, Unset):
            inputs = UNSET
        else:
            inputs = PostCallActionInputs.from_dict(_inputs)

        type_ = cast(Literal["http.post_json"] | Unset, d.pop("type", UNSET))
        if type_ != "http.post_json" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'http.post_json', got '{type_}'")

        post_call_action = cls(
            action_id=action_id,
            execution=execution,
            semantic_key=semantic_key,
            semantic_version=semantic_version,
            inputs=inputs,
            type_=type_,
        )

        return post_call_action
