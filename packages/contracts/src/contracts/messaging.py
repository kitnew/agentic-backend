from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallEventPayload(_Message):
    call_id: UUID
    status: Literal["created", "started", "connected", "ended", "failed"]
    failure_reason: str | None = None


class GenerateCallSummary(_Message):
    command_type: Literal["call.generate_summary.v1"] = "call.generate_summary.v1"
    call_id: UUID
    finalization_id: UUID


class ExecutePostCallAction(_Message):
    command_type: Literal["call.execute_post_call_action.v1"] = (
        "call.execute_post_call_action.v1"
    )
    call_id: UUID
    finalization_id: UUID
    action_id: str = Field(min_length=1, max_length=128)


CommandPayload = Annotated[
    GenerateCallSummary | ExecutePostCallAction,
    Field(discriminator="command_type"),
]


class CommandError(_Message):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    transient: bool


class CommandResult(_Message):
    command_id: UUID
    command_type: Literal[
        "call.generate_summary.v1", "call.execute_post_call_action.v1"
    ]
    status: Literal["succeeded", "failed"]
    output: dict[str, object] | None = None
    error: CommandError | None = None
    attempt: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> CommandResult:
        if self.status == "succeeded":
            if self.output is None or self.error is not None:
                raise ValueError("succeeded command result requires only output")
        elif self.error is None or self.output is not None:
            raise ValueError("failed command result requires only error")
        return self


class MessageEnvelope(_Message):
    message_id: UUID = Field(default_factory=uuid4)
    message_kind: Literal["event", "command", "command_result"]
    message_type: str = Field(min_length=1, max_length=128)
    schema_version: Literal[1] = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID
    causation_id: UUID | None = None
    tenant_id: UUID | None = None
    payload: dict[str, object]


def command_envelope(
    command: GenerateCallSummary | ExecutePostCallAction,
    *,
    tenant_id: UUID,
    correlation_id: UUID,
    causation_id: UUID | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_kind="command",
        message_type=command.command_type,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=command.model_dump(mode="json"),
    )


def parse_command(message: MessageEnvelope) -> CommandPayload:
    if message.message_kind != "command":
        raise ValueError("message is not a command")
    command: GenerateCallSummary | ExecutePostCallAction = TypeAdapter(
        CommandPayload
    ).validate_python(message.payload)
    if command.command_type != message.message_type:
        raise ValueError("command type does not match envelope")
    return command
