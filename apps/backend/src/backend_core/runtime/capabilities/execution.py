import json
from dataclasses import dataclass, field
from typing import cast

from contracts import (
    GoogleSheetsAppendValuesResult,
    ManagedWebhookPostJsonResult,
    TechnicalResult,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True)
class ExecutionOutcome:
    reference: str | None = None
    deduplicated: bool = False
    data: dict[str, JsonValue] = field(default_factory=dict)


class TechnicalResultProjectionError(ValueError):
    pass


def _json_data(value: dict[str, object]) -> dict[str, JsonValue]:
    try:
        decoded = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise TechnicalResultProjectionError(
            "Technical result data is not JSON-compatible"
        ) from error
    if not isinstance(decoded, dict):
        raise TechnicalResultProjectionError("Technical result data must be an object")
    return cast(dict[str, JsonValue], decoded)


def project_execution_outcome(result: TechnicalResult) -> ExecutionOutcome:
    if isinstance(result, GoogleSheetsAppendValuesResult):
        return ExecutionOutcome(
            reference=result.updated_range,
            deduplicated=result.deduplicated,
        )
    if isinstance(result, ManagedWebhookPostJsonResult):
        return ExecutionOutcome(
            reference=result.reference,
            deduplicated=result.deduplicated,
            data=_json_data(result.data),
        )
    raise TechnicalResultProjectionError(
        f"Unsupported technical result type: {type(result).__name__}"
    )
