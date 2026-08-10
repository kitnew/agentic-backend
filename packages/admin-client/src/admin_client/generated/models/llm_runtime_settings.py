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

T = TypeVar("T", bound="LLMRuntimeSettings")


@_attrs_define
class LLMRuntimeSettings:
    """
    Attributes:
        model (str):
        provider (Literal['azure_openai']):
        temperature (float):
    """

    model: str
    provider: Literal["azure_openai"]
    temperature: float

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        provider = self.provider

        temperature = self.temperature

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
                "provider": provider,
                "temperature": temperature,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        model = d.pop("model")

        provider = cast(Literal["azure_openai"], d.pop("provider"))
        if provider != "azure_openai":
            raise ValueError(
                f"provider must match const 'azure_openai', got '{provider}'"
            )

        temperature = d.pop("temperature")

        llm_runtime_settings = cls(
            model=model,
            provider=provider,
            temperature=temperature,
        )

        return llm_runtime_settings
