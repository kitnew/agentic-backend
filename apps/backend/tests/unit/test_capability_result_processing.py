from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend_core.runtime.capabilities.domain import CapabilityValidationError
from backend_core.runtime.capabilities.models import CapabilityInvocation
from backend_core.runtime.capabilities.service import (
    CapabilityInvocationService,
    invocation_response,
)
from contracts import (
    CapabilityInvocationStatus,
    HttpRequestResult,
    WorkerError,
    WorkerResultReport,
)


class Repository:
    def __init__(self, invocation: CapabilityInvocation) -> None:
        self.invocation = invocation
        self.flushed = False

    async def get(self, invocation_id: UUID, *, for_update: bool = False):
        assert for_update
        return self.invocation if invocation_id == self.invocation.id else None

    async def flush(self) -> None:
        self.flushed = True


def invocation() -> CapabilityInvocation:
    execution_id = uuid4()
    return CapabilityInvocation(
        id=uuid4(),
        tenant_id=uuid4(),
        call_id=uuid4(),
        conversation_id=uuid4(),
        tool_call_id="tool-call",
        semantic_key="reservation.create",
        execution_id=execution_id,
        status=CapabilityInvocationStatus.QUEUED,
        canonical_input={},
        worker_context={
            "execution_id": str(execution_id),
            "tenant_id": "tenant-a",
            "action": {"key": "reservation.create", "phase": "runtime"},
        },
        operation_id=uuid4(),
        job_id=uuid4(),
        created_at=datetime.now(UTC),
    )


def report(
    current: CapabilityInvocation, *, failed: bool = False
) -> WorkerResultReport:
    now = datetime.now(UTC)
    return WorkerResultReport(
        job_id=current.job_id,
        capability_invocation_id=current.id,
        status="failed" if failed else "succeeded",
        result=None
        if failed
        else HttpRequestResult(
            result_type="http.request.v1",
            status="succeeded",
            operation_id=current.operation_id,
            data={"status": "submitted"},
        ),
        error=WorkerError(code="provider_error", message="safe", transient=False)
        if failed
        else None,
        attempt=1,
        started_at=now,
        completed_at=now,
    )


@pytest.mark.asyncio
async def test_target_http_result_completes_invocation() -> None:
    current = invocation()
    repository = Repository(current)
    completed = await CapabilityInvocationService(
        repository, None, None, None, None
    ).record_result(report(current))
    assert completed.status is CapabilityInvocationStatus.SUCCEEDED
    assert completed.semantic_result == {"status": "submitted"}
    assert invocation_response(completed).semantic_result == completed.semantic_result
    assert repository.flushed


@pytest.mark.asyncio
async def test_wrong_job_is_rejected_and_failure_is_safe() -> None:
    current = invocation()
    service = CapabilityInvocationService(Repository(current), None, None, None, None)
    with pytest.raises(CapabilityValidationError, match="not found"):
        await service.record_result(
            report(current).model_copy(update={"job_id": uuid4()})
        )
    completed = await service.record_result(report(current, failed=True))
    assert completed.status is CapabilityInvocationStatus.FAILED
    assert completed.error_code == "execution_failed"
    assert completed.error_message == "Capability execution failed"
