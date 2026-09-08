import json
from typing import Any

import jsonata  # type: ignore[import-untyped]

from backend_core.runtime.capabilities.execution import ExecutionOutcome

MAX_MAPPING_INPUT_BYTES = 64_000
MAX_MAPPING_OUTPUT_BYTES = 64_000


class CapabilityValidationError(ValueError):
    def __init__(self, code: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


class JsonataMappingEngine:
    def evaluate(self, expression: str, data: dict[str, Any]) -> object:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > MAX_MAPPING_INPUT_BYTES:
            raise CapabilityValidationError(
                "mapping_input_too_large", "Mapping input is too large"
            )
        try:
            result = jsonata.Jsonata(expression).evaluate(json.loads(encoded))
            output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except Exception as error:
            raise CapabilityValidationError(
                "mapping_failed", "JSONata mapping failed"
            ) from error
        if len(output.encode()) > MAX_MAPPING_OUTPUT_BYTES:
            raise CapabilityValidationError(
                "mapping_output_too_large", "Mapping output is too large"
            )
        return json.loads(output)


def semantic_result(outcome: ExecutionOutcome) -> dict[str, object] | str | None:
    if not isinstance(outcome.data, (dict, str, type(None))):
        raise CapabilityValidationError(
            "invalid_semantic_result",
            "Capability result must be an object, string, or null",
        )
    return outcome.data
