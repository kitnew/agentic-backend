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
from backend_core.runtime.capabilities.service import (
    CapabilityInvocationService,
    invocation_response,
)
from contracts import (
    CapabilityInvocationStatus,
    GoogleSheetsAppendValuesResult,
    ManagedWebhookPostJsonResult,
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


def invocation(plan_type: str) -> CapabilityInvocation:
    now = datetime.now(UTC)
    return CapabilityInvocation(
        id=uuid4(),
        tenant_id=uuid4(),
        call_id=uuid4(),
        conversation_id=uuid4(),
        tool_call_id="tool-call",
        semantic_key="reservation.submit_request",
        semantic_version=1,
        tenant_release_id=uuid4(),
        runtime_bundle_id=uuid4(),
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
                        "semantic_key": "reservation.submit_request",
                        "semantic_version": 1,
                    },
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
    result: GoogleSheetsAppendValuesResult | ManagedWebhookPostJsonResult | None,
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
            "managed_webhook.post_json.v1",
            ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
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
    result: GoogleSheetsAppendValuesResult | ManagedWebhookPostJsonResult,
) -> None:
    current = invocation(plan_type)
    repository = InvocationRepository(current)
    service = CapabilityInvocationService(repository, None, None, None, None, None)

    completed = await service.record_result(report(current, result))

    assert completed.status is CapabilityInvocationStatus.SUCCEEDED
    assert completed.technical_result["result_type"] == result.result_type
    assert completed.semantic_result == {
        "status": "request_submitted",
        "request_reference": (
            result.updated_range
            if isinstance(result, GoogleSheetsAppendValuesResult)
            else result.reference
        ),
        "deduplicated": result.deduplicated,
    }
    assert repository.flushed


@pytest.mark.asyncio
async def test_configured_webhook_result_is_the_validated_agent_result() -> None:
    current = invocation("managed_webhook.post_json.v1")
    current.execution_plan["response"] = {
        "mode": "json",
        "mapping": '{"status": response.body.status}',
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"const": "created"}},
        },
    }
    result = ManagedWebhookPostJsonResult(
        result_type="managed_webhook.post_json.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference=None,
        deduplicated=False,
        data={"status": "created"},
    )
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None, None
    )

    completed = await service.record_result(report(current, result))

    assert completed.semantic_result == {"status": "created"}
    assert invocation_response(completed).semantic_result == {"status": "created"}


@pytest.mark.asyncio
async def test_backend_rejects_worker_result_that_violates_output_schema() -> None:
    current = invocation("managed_webhook.post_json.v1")
    current.execution_plan["response"] = {
        "mode": "status_only",
        "success_output": {"status": "submitted"},
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"const": "submitted"}},
        },
    }
    result = ManagedWebhookPostJsonResult(
        result_type="managed_webhook.post_json.v1",
        status="succeeded",
        operation_id=uuid4(),
        reference=None,
        deduplicated=False,
        data={"status": "wrong"},
    )
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None, None
    )

    with pytest.raises(CapabilityValidationError, match="violates output schema"):
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
        ManagedWebhookPostJsonResult(
            result_type="managed_webhook.post_json.v1",
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


@pytest.mark.parametrize(
    ("reference", "deduplicated"), [("accepted-1", False), (None, True)]
)
def test_semantic_mapper_accepts_execution_outcome_only(
    reference: str | None, deduplicated: bool
) -> None:
    result = semantic_result(
        "reservation.submit_request",
        1,
        ExecutionOutcome(reference=reference, deduplicated=deduplicated),
    )
    assert result.status == "request_submitted"
    assert result.request_reference == reference
    assert result.deduplicated is deduplicated


@pytest.mark.asyncio
async def test_result_plan_mismatch_and_wrong_job_are_rejected() -> None:
    current = invocation("google_sheets.append_values.v1")
    service = CapabilityInvocationService(
        InvocationRepository(current), None, None, None, None, None
    )
    webhook = ManagedWebhookPostJsonResult(
        result_type="managed_webhook.post_json.v1",
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
        InvocationRepository(current), None, None, None, None, None, metrics=metrics
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
