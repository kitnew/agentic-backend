from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="LLMCapabilitiesWrite")


@_attrs_define
class LLMCapabilitiesWrite:
    """
    Attributes:
        kind (Literal['llm']):
        supports_reasoning_effort (bool):
        supports_temperature (bool):
    """

    kind: Literal["llm"]
    supports_reasoning_effort: bool
    supports_temperature: bool

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        supports_reasoning_effort = self.supports_reasoning_effort

        supports_temperature = self.supports_temperature

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "supports_reasoning_effort": supports_reasoning_effort,
                "supports_temperature": supports_temperature,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        kind = cast(Literal["llm"], d.pop("kind"))
        if kind != "llm":
            raise ValueError(f"kind must match const 'llm', got '{kind}'")

        supports_reasoning_effort = d.pop("supports_reasoning_effort")

        supports_temperature = d.pop("supports_temperature")

        llm_capabilities_write = cls(
            kind=kind,
            supports_reasoning_effort=supports_reasoning_effort,
            supports_temperature=supports_temperature,
        )

        return llm_capabilities_write
