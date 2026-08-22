from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_runtime_policy import PlatformRuntimePolicy


T = TypeVar("T", bound="RuntimeDraftWrite")


@_attrs_define
class RuntimeDraftWrite:
    """
    Attributes:
        policy (PlatformRuntimePolicy):
    """

    policy: PlatformRuntimePolicy

    def to_dict(self) -> dict[str, Any]:
        policy = self.policy.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "policy": policy,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_runtime_policy import PlatformRuntimePolicy

        d = dict(src_dict)
        policy = PlatformRuntimePolicy.from_dict(d.pop("policy"))

        runtime_draft_write = cls(
            policy=policy,
        )

        return runtime_draft_write
