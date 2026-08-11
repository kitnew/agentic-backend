from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.managed_webhook_execution import ManagedWebhookExecution


T = TypeVar("T", bound="PostCallAction")


@_attrs_define
class PostCallAction:
    """
    Attributes:
        action_id (str):
        execution (ManagedWebhookExecution):
        semantic_key (str):
        semantic_version (int):
    """

    action_id: str
    execution: ManagedWebhookExecution
    semantic_key: str
    semantic_version: int

    def to_dict(self) -> dict[str, Any]:
        action_id = self.action_id

        execution = self.execution.to_dict()

        semantic_key = self.semantic_key

        semantic_version = self.semantic_version

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "action_id": action_id,
                "execution": execution,
                "semantic_key": semantic_key,
                "semantic_version": semantic_version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.managed_webhook_execution import ManagedWebhookExecution

        d = dict(src_dict)
        action_id = d.pop("action_id")

        execution = ManagedWebhookExecution.from_dict(d.pop("execution"))

        semantic_key = d.pop("semantic_key")

        semantic_version = d.pop("semantic_version")

        post_call_action = cls(
            action_id=action_id,
            execution=execution,
            semantic_key=semantic_key,
            semantic_version=semantic_version,
        )

        return post_call_action
