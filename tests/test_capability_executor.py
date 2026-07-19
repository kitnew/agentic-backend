import asyncio

from app.application.capabilities.boundary import InProcessCapabilityExecutor
from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionStatus,
    CapabilityResult,
    CapabilityStatus,
)
from app.tenants.schemas import TenantContext


class FakeTenantLoader:
    def __init__(self, tenants: dict[str, TenantContext]):
        self.tenants = tenants

    def load(self, tenant_id: str) -> TenantContext:
        return self.tenants[tenant_id]


class FakeRouter:
    def __init__(self, *, fail: bool = False, async_result: bool = False):
        self.fail = fail
        self.async_result = async_result
        self.calls = []

    def execute(self, tenant_context, capability_request):
        self.calls.append((tenant_context, capability_request))
        if self.fail:
            raise RuntimeError("provider exploded")

        result = CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider="fake",
            output={
                "tenant_id": tenant_context.tenant_id,
                "payload": capability_request.input,
            },
            user_message="done",
        )
        if self.async_result:
            return self._async_result(result)
        return result

    async def _async_result(self, result):
        return result


class UnknownRouter:
    def execute(self, tenant_context, capability_request):
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.FAILED,
            provider="fake",
            error="unknown capability",
        )


class ValidationRouter:
    def execute(self, tenant_context, capability_request):
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SKIPPED,
            provider="validation",
            user_message="Choose a future date.",
            error="past_check_in_not_allowed",
        )


def tenant(tenant_id: str) -> TenantContext:
    return TenantContext.model_validate(
        {
            "tenant_id": tenant_id,
            "name": tenant_id,
            "business_type": "restaurant",
            "default_language": "sk",
            "timezone": "Europe/Bratislava",
            "agent": {"profile": "restaurant_assistant"},
        }
    )


def command(
    command_id: str,
    *,
    tenant_id: str = "tenant-1",
    payload=None,
) -> CapabilityCommand:
    return CapabilityCommand(
        command_id=command_id,
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        capability="reservation",
        action="create_request",
        payload=payload or {"value": command_id},
        metadata={},
    )


def test_in_process_capability_executor_success():
    router = FakeRouter()
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader({"tenant-1": tenant("tenant-1")}),
        capability_router=router,
    )

    result = asyncio.run(executor.execute(command("command-1")))

    assert result.command_id == "command-1"
    assert result.status == CapabilityExecutionStatus.SUCCESS
    assert result.result["tenant_id"] == "tenant-1"
    assert result.metadata["provider"] == "fake"
    assert result.metadata["user_message"] == "done"
    assert router.calls[0][1].name == "reservation.create_request"


def test_in_process_capability_executor_unknown_capability_returns_failed_result():
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader({"tenant-1": tenant("tenant-1")}),
        capability_router=UnknownRouter(),
    )

    result = asyncio.run(executor.execute(command("command-unknown")))

    assert result.status == CapabilityExecutionStatus.FAILED
    assert result.error_code == "failed"
    assert result.error_message == "unknown capability"


def test_domain_validation_is_terminal_and_keeps_legacy_skipped_status():
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader({"tenant-1": tenant("tenant-1")}),
        capability_router=ValidationRouter(),
    )

    result = asyncio.run(executor.execute(command("command-validation")))

    assert result.status == CapabilityExecutionStatus.SUCCESS
    assert result.metadata["legacy_status"] == "skipped"
    assert result.metadata["provider"] == "validation"
    assert result.error_message == "past_check_in_not_allowed"


def test_in_process_capability_executor_normalizes_handler_exception():
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader({"tenant-1": tenant("tenant-1")}),
        capability_router=FakeRouter(fail=True),
    )

    result = asyncio.run(executor.execute(command("command-error")))

    assert result.status == CapabilityExecutionStatus.FAILED
    assert result.error_code == "RuntimeError"
    assert result.error_message == "provider exploded"


def test_in_process_capability_executor_isolates_concurrent_tenant_contexts():
    router = FakeRouter(async_result=True)
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader(
            {
                "tenant-1": tenant("tenant-1"),
                "tenant-2": tenant("tenant-2"),
            }
        ),
        capability_router=router,
    )

    async def run():
        return await asyncio.gather(
            executor.execute(command("command-1", tenant_id="tenant-1")),
            executor.execute(command("command-2", tenant_id="tenant-2")),
        )

    first, second = asyncio.run(run())

    assert first.result["tenant_id"] == "tenant-1"
    assert second.result["tenant_id"] == "tenant-2"
    assert first.command_id == "command-1"
    assert second.command_id == "command-2"


def test_in_process_capability_executor_supports_async_router_results():
    executor = InProcessCapabilityExecutor(
        tenant_config_loader=FakeTenantLoader({"tenant-1": tenant("tenant-1")}),
        capability_router=FakeRouter(async_result=True),
    )

    result = asyncio.run(executor.execute(command("command-async")))

    assert result.status == CapabilityExecutionStatus.SUCCESS
    assert result.result["payload"] == {"value": "command-async"}
