from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.llm_defaults_reasoning_effort_type_0 import (
    LLMDefaultsReasoningEffortType0,
)
from ..types import UNSET, Unset

T = TypeVar("T", bound="LLMDefaults")


@_attrs_define
class LLMDefaults:
    """
    Attributes:
        deployment_ref (UUID):
        max_completion_tokens (int):
        reasoning_effort (LLMDefaultsReasoningEffortType0 | None | Unset):
        temperature (float | None | Unset):
    """

    deployment_ref: UUID
    max_completion_tokens: int
    reasoning_effort: LLMDefaultsReasoningEffortType0 | None | Unset = UNSET
    temperature: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        deployment_ref = str(self.deployment_ref)

        max_completion_tokens = self.max_completion_tokens

        reasoning_effort: None | str | Unset
        if isinstance(self.reasoning_effort, Unset):
            reasoning_effort = UNSET
        elif isinstance(self.reasoning_effort, LLMDefaultsReasoningEffortType0):
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
                "deployment_ref": deployment_ref,
                "max_completion_tokens": max_completion_tokens,
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
        deployment_ref = UUID(d.pop("deployment_ref"))

        max_completion_tokens = d.pop("max_completion_tokens")

        def _parse_reasoning_effort(
            data: object,
        ) -> LLMDefaultsReasoningEffortType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reasoning_effort_type_0 = LLMDefaultsReasoningEffortType0(data)

                return reasoning_effort_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(LLMDefaultsReasoningEffortType0 | None | Unset, data)

        reasoning_effort = _parse_reasoning_effort(d.pop("reasoning_effort", UNSET))

        def _parse_temperature(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        temperature = _parse_temperature(d.pop("temperature", UNSET))

        llm_defaults = cls(
            deployment_ref=deployment_ref,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
        )

        return llm_defaults
