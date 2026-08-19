from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="TenantLLMRuntimeOverride")


@_attrs_define
class TenantLLMRuntimeOverride:
    """
    Attributes:
        model (str):
    """

    model: str

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        model = d.pop("model")

        tenant_llm_runtime_override = cls(
            model=model,
        )

        return tenant_llm_runtime_override
