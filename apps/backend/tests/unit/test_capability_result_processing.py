from dataclasses import fields
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    semantic_result,
)
from backend_core.runtime.capabilities.execution import (
    ExecutionOutcome,
    project_execution_outcome,
)
from backend_core.runtime.capabilities.models import CapabilityInvocation
from backend_core.runtime.capabilities.router import report_result
from backend_core.runtime.capabilities.service import (
    CapabilityInvocationService,
    invocation_response,
)
from contracts import (
    CapabilityInvocationStatus,
    GoogleSheetsAppendValuesResult,
    HttpRequestResult,
    WorkerError,
    WorkerResultReport,
)


class InvocationRepository:
    def __init__(self, invocation: CapabilityInvocation) -> None:
        self.invocation = invocation
        self.flushed = False

    async def get(
        self, invocation_id: UUID, *, for_update: bool = False
    ) -> CapabilityInvocation | None:
        assert for_update
        return self.invocation if invocation_id == self.invocation.id else None

    async def flush(self) -> None:
        self.flushed = True


def invocation(
    plan_type: str, *, semantic_key: str = "tenant.request"
) -> CapabilityInvocation:
    now = datetime.now(UTC)
    return CapabilityInvocation(
        id=uuid4(),
        tenant_id=uuid4(),
        call_id=uuid4(),
        conversation_id=uuid4(),
        tool_call_id="tool-call",
        semantic_key=semantic_key,
        semantic_version=1,
        execution_snapshot_id=uuid4(),
        status=CapabilityInvocationStatus.QUEUED,
        canonical_input={},
        execution_plan={
            "plan_type": plan_type,
            **(
                {
                    "integration_id": str(uuid4()),
                    "spreadsheet_id": "sheet",
                    "sheet_name": "Reservations",
                    "append_range": "A:D",
                    "value_input_option": "RAW",
                    "rows": [["id"]],
                    "idempotency": {
                        "operation_id": str(uuid4()),
                        "lookup_range": "A:A",
                        "operation_id_column_index": 0,
                    },
                }
                if plan_type == "google_sheets.append_values.v1"
                else {
                    "integration_id": str(uuid4()),
                    "operation_id": str(uuid4()),
                    "capability": {
                        "semantic_key": semantic_key,
                        "semantic_version": 1,
                    },
                    "method": "POST",
                    "request": {"codec": "none"},
                    "response": {"codec": "none"},
                    "payload": {},
                    "timeout_seconds": 10,
                }
            ),
        },
        operation_id=uuid4(),
        job_id=uuid4(),
        created_at=now,
    )


def report(
    current: CapabilityInvocation,
    result: GoogleSheetsAppendValuesResult | HttpRequestResult | None,
    error: WorkerError | None = None,
) -> WorkerResultReport:
    now = datetime.now(UTC)
    return WorkerResultReport(
        job_id=current.job_id,
        capability_invocation_id=current.id,
        status="succeeded" if result else "failed",
        result=result,
        error=error,
        attempt=1,
        started_at=now,
        completed_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan_type", "result"),
    [
        (
            "google_sheets.append_values.v1",
            GoogleSheetsAppendValuesResult(
                result_type="google_sheets.append_values.v1",
                status="succeeded",
                updated_range="Reservations!A2:D2",
                updated_rows=1,
                deduplicated=False,
            ),
        ),
        (
            "http.request.v1",
            HttpRequestResult(
                result_type="http.request.v1",
                status="succeeded",
                operation_id=uuid4(),
                reference="accepted-1",
                deduplicated=True,
            ),
        ),
    ],
)
async def test_matching_typed_result_completes_invocation(
    plan_type: str,
    result: GoogleSheetsAppendValuesResult | HttpRequestResult,
) -> None:
    current = invocation(plan_type)
    repository = InvocationRepository(current)
    service = CapabilityInvocationService(repository, None, None, None, None)

    completed = await service.record_result(report(current, result))

    assert completed.status is CapabilityInvocationStatus.SUCCEEDED
    assert completed.technical_result["result_type"] == result.result_type
    assert completed.semantic_result == (
        {} if isinstance(result, GoogleSheetsAppendValuesResult) else None
    )
    assert repository.flushed


@pytest.mark.asyncio
async def test_configured_http_result_is_the_validated_agent_result() -> None:
    current = invocation("http.request.v1", semantic_key="tenant.lookup")
    current.execution_plan["response"] = {
        "codec": "json",
        "mapping": {"status": {"$expr": "response.body.status"}},
    }
    result = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference=None,
        deduplicated=False,
        data={"status": "created"},
    )
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None
    )

    completed = await report_result(report(current, result), service)

    assert completed.semantic_result == {"status": "created"}
    assert invocation_response(completed).semantic_result == completed.semantic_result


@pytest.mark.asyncio
async def test_check_availability_uses_validated_canonical_result() -> None:
    current = invocation(
        "http.request.v1", semantic_key="reservation.check_availability"
    )
    current.execution_plan["capability"] = {
        "semantic_key": "reservation.check_availability",
        "semantic_version": 1,
    }
    current.execution_plan["result_schema"] = {
        "type": "object",
        "required": ["status", "available_rooms"],
        "properties": {
            "status": {"type": "string"},
            "available_rooms": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    result = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference=None,
        deduplicated=False,
        data={"status": "available", "available_rooms": 2},
    )
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None
    )

    completed = await service.record_result(report(current, result))

    assert completed.status is CapabilityInvocationStatus.SUCCEEDED
    assert completed.semantic_result == {
        "status": "available",
        "available_rooms": 2,
    }
    assert invocation_response(completed).semantic_result == completed.semantic_result


@pytest.mark.asyncio
async def test_backend_rejects_http_result_that_violates_result_schema() -> None:
    current = invocation("http.request.v1")
    current.execution_plan["result_schema"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {"status": {"const": "submitted"}},
    }
    result = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference=None,
        deduplicated=False,
        data={"status": "wrong"},
    )
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None
    )

    with pytest.raises(CapabilityValidationError, match="violates result_schema"):
        await service.record_result(report(current, result))


def test_technical_results_project_to_provider_neutral_outcomes() -> None:
    sheets = project_execution_outcome(
        GoogleSheetsAppendValuesResult(
            result_type="google_sheets.append_values.v1",
            status="succeeded",
            updated_range="Reservations!A2:D2",
            updated_rows=1,
            deduplicated=True,
        )
    )
    webhook = project_execution_outcome(
        HttpRequestResult(
            result_type="http.request.v1",
            status="succeeded",
            operation_id=uuid4(),
            reference=None,
            deduplicated=False,
            data={"accepted": True},
        )
    )
    assert sheets == ExecutionOutcome(reference="Reservations!A2:D2", deduplicated=True)
    assert webhook == ExecutionOutcome(
        reference=None, deduplicated=False, data={"accepted": True}
    )
    assert {field.name for field in fields(ExecutionOutcome)} == {
        "reference",
        "deduplicated",
        "data",
    }


def test_unknown_technical_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported technical result type"):
        project_execution_outcome(object())  # type: ignore[arg-type]


def test_declarative_capability_uses_provider_data() -> None:
    result = semantic_result(
        ExecutionOutcome(data={"status": "available", "available_rooms": 2})
    )

    assert result == {"status": "available", "available_rooms": 2}


@pytest.mark.asyncio
async def test_result_plan_mismatch_and_wrong_job_are_rejected() -> None:
    current = invocation("google_sheets.append_values.v1")
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None
    )
    webhook = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference="accepted-1",
        deduplicated=False,
    )
    with pytest.raises(CapabilityValidationError, match="does not match"):
        await service.record_result(report(current, webhook))
    wrong_job = report(
        current,
        GoogleSheetsAppendValuesResult(
            result_type="google_sheets.append_values.v1",
            status="succeeded",
            updated_range="Reservations!A2:D2",
            updated_rows=1,
            deduplicated=False,
        ),
    ).model_copy(update={"job_id": uuid4()})
    with pytest.raises(CapabilityValidationError, match="not found"):
        await service.record_result(wrong_job)


@pytest.mark.asyncio
async def test_failed_result_persists_typed_error_and_terminal_replay_is_harmless() -> (
    None
):
    current = invocation("google_sheets.append_values.v1")

    class Metrics:
        def __init__(self) -> None:
            self.calls = 0

        def capability_completed(self, **_kwargs) -> None:
            self.calls += 1

    metrics = Metrics()
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None, metrics=metrics
    )
    failed = report(
        current,
        None,
        WorkerError(code="provider_timeout", message="timed out", transient=True),
    )

    completed = await service.record_result(failed)
    replayed = await service.record_result(failed)

    assert completed is replayed
    assert completed.status is CapabilityInvocationStatus.FAILED
    assert metrics.calls == 1
    assert completed.technical_result == {
        "error": {
            "code": "provider_timeout",
            "message": "timed out",
            "transient": True,
        }
    }
