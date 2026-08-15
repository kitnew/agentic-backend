from __future__ import annotations

import re
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, cast

from contracts import CalculatorRequest
from livekit import agents
from livekit.agents import llm
from pydantic import ValidationError

from voice_agent.observability import record_capability_execution

CALCULATOR_DESCRIPTION = (
    "Perform exactly one arithmetic operation per call. Use this whenever exact arithmetic is required. "
    "For multi-step calculations, call it sequentially and pass each result to the next call. "
    "The calculator does not interpret the business meaning of operands. "
    "percentage(A, B) returns B percent of A."
)

_DECIMAL_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)


def _decimal(value: str) -> Decimal:
    if not _DECIMAL_PATTERN.fullmatch(value):
        raise ValueError("operands must be decimal values")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("operands must be decimal values") from exc
    if not result.is_finite():
        raise ValueError("operands must be finite decimal values")
    return result


def _canonical(value: Decimal) -> str:
    if not value:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def calculate(request: CalculatorRequest) -> str:
    operands = [_decimal(value) for value in request.operands]
    precision = max(
        28, sum(max(len(value.as_tuple().digits), 1) for value in operands) + 50
    )
    with localcontext() as context:
        context.prec = precision
        if request.operation == "add":
            result = sum(operands, Decimal(0))
        elif request.operation == "multiply":
            result = Decimal(1)
            for operand in operands:
                result *= operand
        elif request.operation == "subtract":
            result = operands[0] - operands[1]
        elif request.operation == "divide":
            if not operands[1]:
                raise ZeroDivisionError("cannot divide by zero")
            result = operands[0] / operands[1]
        else:
            result = operands[0] * operands[1] / Decimal(100)
    return _canonical(result)


def calculator_tool(
    capability_recorder: Callable[..., None] | None = None,
) -> llm.RawFunctionTool:
    recorder = capability_recorder or record_capability_execution

    async def invoke(
        _context: agents.RunContext[Any],
        raw_arguments: dict[str, object],
    ) -> dict[str, object]:
        started = time.perf_counter()
        status = "failed"
        error_type: str | None = None
        try:
            request = CalculatorRequest.model_validate(raw_arguments)
            result: dict[str, object] = {"result": calculate(request)}
            status = "ok"
            return result
        except ZeroDivisionError:
            error_type = "division_by_zero"
            return {
                "status": "failed",
                "error_code": "division_by_zero",
                "message": "The calculator cannot divide by zero",
            }
        except (ValidationError, ValueError) as exc:
            error_type = "invalid_input"
            message = "Invalid calculator input"
            if (
                isinstance(exc, ValueError)
                and not isinstance(exc, ValidationError)
                and str(exc)
            ):
                message = str(exc)
            return {
                "status": "failed",
                "error_code": "invalid_input",
                "message": message,
            }
        finally:
            recorder(
                name="calculator.calculate",
                version="1",
                status=status,
                duration_seconds=time.perf_counter() - started,
                error_type=error_type,
            )

    return cast(
        llm.RawFunctionTool,
        agents.function_tool(
            raw_schema={
                "name": "calculator",
                "description": CALCULATOR_DESCRIPTION,
                "parameters": CalculatorRequest.model_json_schema(),
            }
        )(invoke),
    )
