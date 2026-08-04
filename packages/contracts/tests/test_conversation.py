from datetime import UTC, datetime
from uuid import uuid4

import pytest
from contracts import AppendConversationMessage, ConversationMessageRole
from pydantic import ValidationError


def test_append_conversation_message_round_trip() -> None:
    payload = AppendConversationMessage(
        message_id=uuid4(),
        role=ConversationMessageRole.USER,
        content=" hello ",
        interrupted=False,
        source_created_at=datetime.now(UTC),
    )
    assert (
        AppendConversationMessage.model_validate_json(payload.model_dump_json())
        == payload
    )


def test_append_conversation_message_forbids_blank_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AppendConversationMessage(
            message_id=uuid4(),
            role="user",
            content="   ",
            interrupted=False,
        )
    with pytest.raises(ValidationError):
        AppendConversationMessage(
            message_id=uuid4(),
            role="user",
            content="hello",
            interrupted=False,
            extra="nope",
        )


def test_append_conversation_message_rejects_naive_source_time() -> None:
    with pytest.raises(ValidationError):
        AppendConversationMessage(
            message_id=uuid4(),
            role="assistant",
            content="hello",
            interrupted=True,
            source_created_at=datetime.now(UTC).replace(tzinfo=None),
        )
