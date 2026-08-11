from uuid import uuid4

import pytest
from contracts import (
    ExecutePostCallAction,
    GenerateCallSummary,
    ManagedWebhookCapability,
    ManagedWebhookPostJsonPlan,
    ManagedWebhookPostJsonResult,
    command_envelope,
)
from job_worker.command_worker import CommandWorker, ExecutePostCallActionHandler
from job_worker.worker import ExecutionError, Settings


class Redis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.values: dict[str, str] = {}
        self.acks: list[tuple[str, str, str]] = []

    async def xadd(self, stream, fields):
        self.streams.setdefault(stream, []).append(fields)
        return "1-0"

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value

    async def xack(self, stream, group, message_id):
        self.acks.append((stream, group, message_id))


def settings() -> Settings:
    return Settings(
        redis_url="redis://redis",
        stream="capability:jobs",
        group="capability-workers",
        consumer="worker-1",
        dead_letter_stream="capability:jobs:dead-letter",
        backend_url="http://backend",
        backend_audience="backend",
        service_secret="secret",
        credential_file_map_json="{}",
        max_retries=1,
    )


def message():
    call_id = uuid4()
    return command_envelope(
        GenerateCallSummary(call_id=call_id, finalization_id=uuid4()),
        tenant_id=uuid4(),
        correlation_id=call_id,
    )


@pytest.mark.asyncio
async def test_dispatches_by_type_publishes_result_and_deduplicates() -> None:
    redis = Redis()
    calls = 0

    async def handle(command, envelope):
        nonlocal calls
        calls += 1
        return {"summary": "done"}

    worker = CommandWorker(
        settings(), redis, {"call.generate_summary.v1": handle}
    )
    envelope = message()
    fields = {"message": envelope.model_dump_json()}

    await worker.handle("1-0", fields)
    await worker.handle("2-0", fields)

    assert calls == 1
    assert len(redis.streams["application:command-results"]) == 2
    assert len(redis.acks) == 2


@pytest.mark.asyncio
async def test_transient_failure_retries_then_reports_and_dead_letters() -> None:
    redis = Redis()

    async def fail(command, envelope):
        raise ExecutionError("provider_timeout", "timed out", transient=True)

    worker = CommandWorker(
        settings(), redis, {"call.generate_summary.v1": fail}
    )
    envelope = message()

    await worker.handle("1-0", {"message": envelope.model_dump_json()})
    retried = redis.streams["application:commands"][0]
    assert retried["attempt"] == "2"

    await worker.handle("2-0", retried)

    assert redis.streams["application:commands:dead-letter"][0][
        "error_code"
    ] == "provider_timeout"
    assert len(redis.streams["application:command-results"]) == 1


@pytest.mark.asyncio
async def test_post_call_action_stays_logical_and_uses_generic_webhook_handler() -> None:
    class Backend:
        async def post_call_action(
            self, call_id, finalization_id, action_id, command_id
        ):
            assert action_id == "notify"
            return ManagedWebhookPostJsonPlan(
                plan_type="managed_webhook.post_json.v1",
                connection_ref="customer-hook",
                operation_id=command_id,
                capability=ManagedWebhookCapability(
                    semantic_key="post_call.notify", semantic_version=1
                ),
                payload={"summary": "done"},
                timeout_seconds=10,
            )

    class Webhooks:
        async def execute(self, plan):
            return ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference="accepted",
                deduplicated=False,
            )

    command = ExecutePostCallAction(
        call_id=uuid4(), finalization_id=uuid4(), action_id="notify"
    )
    envelope = command_envelope(
        command, tenant_id=uuid4(), correlation_id=command.call_id
    )

    output = await ExecutePostCallActionHandler(
        Backend(), Webhooks()  # type: ignore[arg-type]
    )(command, envelope)

    assert output["reference"] == "accepted"
    assert "make" not in envelope.model_dump_json().lower()
