import asyncio
import json
from collections import defaultdict, deque
from datetime import datetime

from app.api.dependencies import get_capability_executor
from app.application.capabilities.boundary import InProcessCapabilityExecutor
from app.application.capabilities.executor import BackendCapabilityExecutor
from app.application.capabilities.redis_executor import RedisCapabilityExecutor
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
    CapabilityRequest,
)
from app.core.config import CapabilitySettings
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.tenants.loader import TenantConfigLoader
from app.tenants.schemas import TenantContext
from app.workers.capability_worker import CapabilityWorker, WorkerCommandExecutor
from redis.exceptions import ResponseError


def settings(**changes) -> CapabilitySettings:
    values = CapabilitySettings().__dict__ | {
        "result_timeout_seconds": 0.05,
        "pending_idle_seconds": 0.05,
    }
    values.update(changes)
    return CapabilitySettings(**values)


def command(command_id="command-1", **changes) -> CapabilityCommand:
    values = {
        "command_id": command_id,
        "tenant_id": "tenant-1",
        "conversation_id": "conversation-1",
        "call_session_id": "session-1",
        "capability": "reservation",
        "action": "create_request",
        "payload": {"guest_name": "Ada"},
        "idempotency_key": None,
        "metadata": {"call_session_id": "session-1", "marker": command_id},
    }
    values.update(changes)
    return CapabilityCommand(**values)


def result(command_id="command-1", *, success=True, metadata=None):
    return CapabilityExecutionResult(
        command_id=command_id,
        status=(
            CapabilityExecutionStatus.SUCCESS
            if success
            else CapabilityExecutionStatus.FAILED
        ),
        result={"ok": True} if success else None,
        error_code=None if success else "provider_failed",
        error_message=None if success else "provider failed",
        execution_duration_ms=2,
        metadata=metadata or {},
    )


class ExecutorRedis:
    def __init__(self, responses=None, *, error=None):
        self.responses = defaultdict(deque)
        for key, values in (responses or {}).items():
            self.responses[key].extend(values)
        self.error = error
        self.published = []

    async def xadd(self, stream, fields):
        if self.error:
            raise self.error
        self.published.append((stream, fields))
        return "1-0"

    async def blpop(self, key, timeout):
        if self.responses[key]:
            return key, self.responses[key].popleft()
        return None


class WorkerRedis:
    def __init__(self):
        self.values = {}
        self.lists = defaultdict(list)
        self.transactions = []
        self.dlq = []
        self.acked = []
        self.deleted_entries = []
        self.claim_response = ("0-0", [], [])

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def xautoclaim(self, *args, **kwargs):
        return self.claim_response

    def pipeline(self, *, transaction):
        assert transaction is True
        return FakePipeline(self)

    def apply(self, name, args, kwargs):
        if name == "rpush":
            self.lists[args[0]].append(args[1])
        elif name == "set":
            self.values[args[0]] = args[1]
        elif name == "delete":
            for key in args:
                self.values.pop(key, None)
        elif name == "xadd":
            self.dlq.append((args[0], args[1]))
        elif name == "xack":
            self.acked.append(args)
        elif name == "xdel":
            self.deleted_entries.append(args)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.commands.append((name, args, kwargs))
            return self

        return queue

    async def execute(self):
        self.redis.transactions.append(self.commands)
        for name, args, kwargs in self.commands:
            self.redis.apply(name, args, kwargs)
        return [True] * len(self.commands)


class SequenceExecutor:
    def __init__(self, outcomes, *, delay=0):
        self.outcomes = deque(outcomes)
        self.delay = delay
        self.calls = []

    async def execute(self, capability_command):
        self.calls.append(capability_command)
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.outcomes.popleft() if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return result(
            capability_command.command_id,
            success=outcome,
            metadata=capability_command.metadata,
        )


class GroupRedis(WorkerRedis):
    def __init__(self, error=None):
        super().__init__()
        self.error = error

    async def xgroup_create(self, *args, **kwargs):
        if self.error:
            raise self.error
        return True


def test_settings_validate_environment(monkeypatch):
    monkeypatch.setenv("CAPABILITY_EXECUTION_MODE", "redis")
    monkeypatch.setenv("CAPABILITY_MAX_RETRIES", "-1")
    try:
        CapabilitySettings.from_env()
    except ValueError as exc:
        assert "max_retries" in str(exc)
    else:
        raise AssertionError("negative retries must fail")


def test_dependency_selects_both_modes(monkeypatch):
    loader = TenantConfigLoader()
    router = CapabilityRouter()
    monkeypatch.setenv("CAPABILITY_EXECUTION_MODE", "in_process")
    assert isinstance(get_capability_executor(loader, router), InProcessCapabilityExecutor)
    monkeypatch.setenv("CAPABILITY_EXECUTION_MODE", "redis")
    assert isinstance(get_capability_executor(loader, router), RedisCapabilityExecutor)


def test_redis_executor_publishes_full_command_and_correlates_strictly():
    config = settings()
    expected = result().model_dump_json()
    redis = ExecutorRedis(
        {
            config.result_key("command-1"): [
                "not-json",
                result("wrong-command").model_dump_json(),
                expected,
            ]
        }
    )

    received = asyncio.run(
        RedisCapabilityExecutor(settings=config, redis_client=redis).execute(command())
    )

    assert received.command_id == "command-1"
    assert redis.published[0][0] == "capability:commands"
    assert json.loads(redis.published[0][1]["command"]) == command().model_dump(mode="json")


def test_redis_executor_isolates_concurrent_results():
    config = settings()
    redis = ExecutorRedis(
        {
            config.result_key("one"): [result("one", metadata={"session": "a"}).model_dump_json()],
            config.result_key("two"): [result("two", metadata={"session": "b"}).model_dump_json()],
        }
    )

    async def run():
        executor = RedisCapabilityExecutor(settings=config, redis_client=redis)
        return await asyncio.gather(executor.execute(command("one")), executor.execute(command("two")))

    one, two = asyncio.run(run())
    assert (one.command_id, one.metadata["session"]) == ("one", "a")
    assert (two.command_id, two.metadata["session"]) == ("two", "b")


def test_redis_executor_normalizes_timeout_connection_and_serialization():
    config = settings()
    timeout = asyncio.run(
        RedisCapabilityExecutor(settings=config, redis_client=ExecutorRedis()).execute(command())
    )
    connection = asyncio.run(
        RedisCapabilityExecutor(
            settings=config,
            redis_client=ExecutorRedis(error=ConnectionError("offline")),
        ).execute(command())
    )
    bad_command = command(metadata={"bad": object()})
    bad_redis = ExecutorRedis()
    serialization = asyncio.run(
        RedisCapabilityExecutor(settings=config, redis_client=bad_redis).execute(bad_command)
    )

    assert timeout.error_code == "capability_result_timeout"
    assert connection.error_code == "redis_error"
    assert serialization.error_code == "serialization_error"
    assert bad_redis.published == []


def test_redis_executor_does_not_cut_off_long_running_capabilities():
    client = RedisCapabilityExecutor(settings=settings())._new_client()

    assert client.connection_pool.connection_kwargs["socket_timeout"] is None


def test_worker_success_is_stored_before_ack_and_attempt_is_deleted():
    config = settings()
    redis = WorkerRedis()
    executor = SequenceExecutor([True])
    worker = CapabilityWorker(redis, settings=config, executor=executor)

    asyncio.run(worker.process_entry("1-0", {"command": command().model_dump_json()}))

    names = [item[0] for item in redis.transactions[0]]
    assert names.index("rpush") < names.index("xack")
    assert CapabilityExecutionResult.model_validate_json(
        redis.lists[config.result_key("command-1")][0]
    ).status == CapabilityExecutionStatus.SUCCESS
    assert config.completion_key("command-1") in redis.values
    assert config.attempt_key("1-0") not in redis.values
    assert len(executor.calls) == 1


def test_worker_retries_with_backoff_then_dead_letters():
    config = settings(max_retries=3)
    redis = WorkerRedis()
    executor = SequenceExecutor([False])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = CapabilityWorker(redis, settings=config, executor=executor, sleep=sleep)
    asyncio.run(worker.process_entry("2-0", {"command": command().model_dump_json()}))

    assert len(executor.calls) == 4
    assert {call.command_id for call in executor.calls} == {"command-1"}
    assert delays == [1, 2, 4]
    assert redis.dlq[0][0] == config.dead_letter_stream
    assert redis.dlq[0][1]["attempts"] == "4"
    assert CapabilityExecutionResult.model_validate_json(
        redis.lists[config.result_key("command-1")][0]
    ).status == CapabilityExecutionStatus.FAILED


def test_worker_retry_preserves_one_durable_tool_identity(monkeypatch):
    redis = WorkerRedis()
    provider = SequenceExecutor([False, True])
    persisted = []
    monkeypatch.setattr(
        "app.workers.capability_worker._persist_tool_result",
        lambda capability_command, execution_result: persisted.append(
            (capability_command.command_id, execution_result.status)
        ),
    )
    durable = command(
        "durable-tool-1",
        metadata={"durable_tool_call_id": "durable-tool-1"},
    )
    worker = CapabilityWorker(
        redis,
        settings=settings(max_retries=1),
        executor=WorkerCommandExecutor(provider),
        sleep=lambda _delay: asyncio.sleep(0),
    )

    asyncio.run(worker.process_entry("durable-1", {"command": durable.model_dump_json()}))

    assert [call.command_id for call in provider.calls] == [
        "durable-tool-1",
        "durable-tool-1",
    ]
    assert persisted == [("durable-tool-1", CapabilityExecutionStatus.SUCCESS)]


def test_worker_normalizes_provider_exception_and_malformed_commands():
    config = settings(max_retries=0)
    exception_redis = WorkerRedis()
    worker = CapabilityWorker(
        exception_redis,
        settings=config,
        executor=SequenceExecutor([RuntimeError("boom")]),
    )
    asyncio.run(worker.process_entry("3-0", {"command": command().model_dump_json()}))
    exception_result = CapabilityExecutionResult.model_validate_json(
        exception_redis.lists[config.result_key("command-1")][0]
    )

    malformed_redis = WorkerRedis()
    malformed = json.dumps({"command_id": "broken-1", "metadata": {"session": "x"}})
    asyncio.run(
        CapabilityWorker(malformed_redis, settings=config).process_entry(
            "4-0", {"command": malformed}
        )
    )
    malformed_result = CapabilityExecutionResult.model_validate_json(
        malformed_redis.lists[config.result_key("broken-1")][0]
    )

    assert exception_result.error_code == "RuntimeError"
    assert malformed_result.error_code == "serialization_error"
    assert malformed_redis.dlq[0][1]["command"] == malformed


def test_worker_recovers_pending_entries():
    redis = WorkerRedis()
    redis.claim_response = (
        "0-0",
        [(b"5-0", {b"command": command("recovered").model_dump_json()})],
        [],
    )
    worker = CapabilityWorker(redis, settings=settings(), executor=SequenceExecutor([True]))

    recovered = asyncio.run(worker.recover_pending(1))

    assert recovered[0][0] == "5-0"
    assert b"command" in recovered[0][1]


def test_worker_group_creation_only_tolerates_busygroup():
    busy = CapabilityWorker(
        GroupRedis(ResponseError("BUSYGROUP Consumer Group name already exists")),
        settings=settings(),
        executor=SequenceExecutor([True]),
    )
    asyncio.run(busy.create_group())

    worker = CapabilityWorker(
        GroupRedis(ResponseError("ERR invalid stream")),
        settings=settings(),
        executor=SequenceExecutor([True]),
    )
    try:
        asyncio.run(worker.create_group())
    except ResponseError as exc:
        assert "invalid stream" in str(exc)
    else:
        raise AssertionError("non-BUSYGROUP errors must not be ignored")


def test_uncorrelated_malformed_command_only_reaches_dead_letter_stream():
    config = settings(max_retries=0)
    redis = WorkerRedis()

    asyncio.run(
        CapabilityWorker(redis, settings=config).process_entry(
            "malformed-1", {"command": "not-json"}
        )
    )

    assert redis.lists == {}
    assert redis.dlq[0][1]["command_id"] == ""
    assert redis.acked


def test_worker_idempotency_invokes_provider_once_and_preserves_current_session():
    config = settings(max_retries=0)
    redis = WorkerRedis()
    executor = SequenceExecutor([True], delay=0.01)
    delays = []

    async def yielding_sleep(delay):
        delays.append(delay)
        await asyncio.sleep(0)

    worker = CapabilityWorker(
        redis,
        settings=config,
        executor=executor,
        sleep=yielding_sleep,
    )
    first = command("first", idempotency_key="same", call_session_id="session-a")
    second = command(
        "second",
        idempotency_key="same",
        call_session_id="session-b",
        metadata={"call_session_id": "session-b", "marker": "second"},
    )

    async def run():
        await asyncio.gather(
            worker.process_entry("6-0", {"command": first.model_dump_json()}),
            worker.process_entry("7-0", {"command": second.model_dump_json()}),
        )

    asyncio.run(run())
    reused = CapabilityExecutionResult.model_validate_json(
        redis.lists[config.result_key("second")][0]
    )

    assert len(executor.calls) == 1
    assert reused.command_id == "second"
    assert reused.metadata["call_session_id"] == "session-b"
    assert reused.metadata["idempotency_reused"] is True


def test_worker_scopes_idempotency_by_tenant():
    config = settings(max_retries=0)
    redis = WorkerRedis()
    executor = SequenceExecutor([True], delay=0.01)
    worker = CapabilityWorker(redis, settings=config, executor=executor)
    first = command("tenant-a", tenant_id="a", idempotency_key="same")
    second = command("tenant-b", tenant_id="b", idempotency_key="same")

    async def run():
        await asyncio.gather(
            worker.process_entry("8-0", {"command": first.model_dump_json()}),
            worker.process_entry("9-0", {"command": second.model_dump_json()}),
        )

    asyncio.run(run())
    assert {item.tenant_id for item in executor.calls} == {"a", "b"}


class ToolCallRepository:
    def __init__(self):
        self.calls = []

    def create(self, tool_call):
        self.calls.append(tool_call)
        return tool_call


class CapturingExecutor:
    def __init__(self):
        self.commands = []

    async def execute(self, capability_command):
        self.commands.append(capability_command)
        return result(capability_command.command_id, metadata=capability_command.metadata)


def test_sync_bridge_runs_inside_active_loop_and_merges_message_metadata():
    message = Message(
        id="message-1",
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        channel="voice",
        role=MessageRole.USER,
        content="reserve",
        status=MessageStatus.PROCESSING,
        metadata={
            "call_session_id": "session-from-message",
            "idempotency_key": "message-key",
            "source": "message",
        },
        created_at=datetime.now(),
    )
    capturing = CapturingExecutor()
    backend = BackendCapabilityExecutor(
        tenant_context=TenantContext.model_validate(
            {
                "tenant_id": "tenant-1",
                "name": "Tenant",
                "business_type": "restaurant",
                "default_language": "en",
                "timezone": "UTC",
                "agent": {"profile": "restaurant_assistant"},
            }
        ),
        message=message,
        capability_router=CapabilityRouter(),
        tool_call_repository=ToolCallRepository(),
        capability_executor=capturing,
    )

    async def run():
        return backend.execute(
            CapabilityRequest(
                name="reservation.create_request",
                metadata={"source": "capability"},
            )
        )

    execution = asyncio.run(run())
    published = capturing.commands[0]

    assert execution.result.status.value == "success"
    assert published.idempotency_key == "message-key"
    assert published.call_session_id == "session-from-message"
    assert published.metadata["source"] == "capability"


def test_worker_routes_internal_call_finalization_without_exposing_capability(monkeypatch):
    calls = []

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    async def finalize(_db, call_session_id):
        calls.append(call_session_id)
        return {"call_session_id": call_session_id, "finalization_status": "completed"}

    monkeypatch.setattr("app.workers.capability_worker.SessionLocal", Db)
    monkeypatch.setattr("app.workers.capability_worker.finalize_call", finalize)
    internal = command(
        "finalize-1",
        capability="call",
        action="finalize",
        call_session_id="call-1",
        payload={"call_session_id": "call-1"},
    )
    execution = asyncio.run(WorkerCommandExecutor().execute(internal))
    assert execution.status == CapabilityExecutionStatus.SUCCESS
    assert calls == ["call-1"]
