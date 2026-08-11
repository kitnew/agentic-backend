from uuid import uuid4

import pytest
from contracts import (
    CommandError,
    CommandResult,
    GenerateCallSummary,
    MessageEnvelope,
    command_envelope,
    parse_command,
)
from pydantic import ValidationError


def test_versioned_command_round_trip_and_type_validation() -> None:
    call_id = uuid4()
    command = GenerateCallSummary(call_id=call_id, finalization_id=uuid4())
    envelope = command_envelope(
        command, tenant_id=uuid4(), correlation_id=call_id
    )

    parsed = MessageEnvelope.model_validate_json(envelope.model_dump_json())

    assert parsed.schema_version == 1
    assert parse_command(parsed) == command
    with pytest.raises(ValueError, match="does not match"):
        parse_command(parsed.model_copy(update={"message_type": "wrong.v1"}))


def test_command_result_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError):
        CommandResult(
            command_id=uuid4(),
            command_type="call.generate_summary.v1",
            status="failed",
            output={},
            error=CommandError(code="failed", message="failed", transient=False),
            attempt=1,
        )
