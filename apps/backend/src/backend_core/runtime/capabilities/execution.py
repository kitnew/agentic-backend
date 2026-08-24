import json
from dataclasses import dataclass, field

from contracts import (
    GoogleSheetsAppendValuesResult,
    HttpRequestResult,
    TechnicalResult,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True)
class ExecutionOutcome:
    reference: str | None = None
    deduplicated: bool = False
    data: object = field(default_factory=dict)


class TechnicalResultProjectionError(ValueError):
    pass


def _json_data(value: object) -> object:
    try:
        decoded = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise TechnicalResultProjectionError(
            "Technical result data is not JSON-compatible"
        ) from error
    return decoded


def project_execution_outcome(result: TechnicalResult) -> ExecutionOutcome:
    if isinstance(result, GoogleSheetsAppendValuesResult):
        return ExecutionOutcome(
            reference=result.updated_range,
            deduplicated=result.deduplicated,
        )
    if isinstance(result, HttpRequestResult):
        return ExecutionOutcome(
            reference=result.reference,
            deduplicated=result.deduplicated,
            data=_json_data(result.data),
        )
    raise TechnicalResultProjectionError(
        f"Unsupported technical result type: {type(result).__name__}"
    )
