from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.tenant_llm_runtime_override_reasoning_effort_type_0 import (
    TenantLLMRuntimeOverrideReasoningEffortType0,
)
from ..types import UNSET, Unset

T = TypeVar("T", bound="TenantLLMRuntimeOverride")


@_attrs_define
class TenantLLMRuntimeOverride:
    """
    Attributes:
        model (str):
        reasoning_effort (None | TenantLLMRuntimeOverrideReasoningEffortType0 | Unset):
        temperature (float | None | Unset):
    """

    model: str
    reasoning_effort: None | TenantLLMRuntimeOverrideReasoningEffortType0 | Unset = (
        UNSET
    )
    temperature: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        reasoning_effort: None | str | Unset
        if isinstance(self.reasoning_effort, Unset):
            reasoning_effort = UNSET
        elif isinstance(
            self.reasoning_effort, TenantLLMRuntimeOverrideReasoningEffortType0
        ):
            reasoning_effort = self.reasoning_effort.value
        else:
            reasoning_effort = self.reasoning_effort

        temperature: float | None | Unset
        if isinstance(self.temperature, Unset):
            temperature = UNSET
        else:
            temperature = self.temperature

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
            }
        )
        if reasoning_effort is not UNSET:
            field_dict["reasoning_effort"] = reasoning_effort
        if temperature is not UNSET:
            field_dict["temperature"] = temperature

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        model = d.pop("model")

        def _parse_reasoning_effort(
            data: object,
        ) -> None | TenantLLMRuntimeOverrideReasoningEffortType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reasoning_effort_type_0 = TenantLLMRuntimeOverrideReasoningEffortType0(
                    data
                )

                return reasoning_effort_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | TenantLLMRuntimeOverrideReasoningEffortType0 | Unset, data
            )

        reasoning_effort = _parse_reasoning_effort(d.pop("reasoning_effort", UNSET))

        def _parse_temperature(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        temperature = _parse_temperature(d.pop("temperature", UNSET))

        tenant_llm_runtime_override = cls(
            model=model,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
        )

        return tenant_llm_runtime_override
