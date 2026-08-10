from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from contracts import (
    CalculatorRequest,
    ExecutionPlan,
    GoogleSheetsAppendValuesPlan,
    IntegrationJob,
    RuntimeCapabilityDefinition,
    TechnicalResult,
    WorkerResultReport,
)
from pydantic import TypeAdapter, ValidationError


def plan() -> GoogleSheetsAppendValuesPlan:
    operation_id = uuid4()
    return GoogleSheetsAppendValuesPlan(
        plan_type="google_sheets.append_values.v1",
        credential_ref="tenant-a-sheets",
        spreadsheet_id="sheet",
        sheet_name="Reservations",
        append_range="A:G",
        value_input_option="RAW",
        rows=[[str(operation_id), "Alice", 2, True, None]],
        idempotency={
            "operation_id": operation_id,
            "lookup_range": "A:A",
            "operation_id_column_index": 0,
        },
    )


def test_job_and_result_contracts_round_trip() -> None:
    now = datetime.now(UTC)
    job = IntegrationJob(
        job_id=uuid4(),
        capability_invocation_id=uuid4(),
        execution_plan=plan(),
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    assert IntegrationJob.model_validate_json(job.model_dump_json()) == job
    report = WorkerResultReport(
        job_id=job.job_id,
        capability_invocation_id=job.capability_invocation_id,
        status="succeeded",
        result={
            "result_type": "google_sheets.append_values.v1",
            "status": "succeeded",
            "updated_range": "Reservations!A2:E2",
            "updated_rows": 1,
            "deduplicated": False,
        },
        attempt=1,
        started_at=now,
        completed_at=now,
    )
    assert WorkerResultReport.model_validate_json(report.model_dump_json()) == report


def test_result_discriminator_and_outcome_invariants_are_enforced() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        TypeAdapter(TechnicalResult).validate_python({"result_type": "unknown.v1"})
    with pytest.raises(ValidationError):
        WorkerResultReport.model_validate(
            {
                "job_id": str(uuid4()),
                "capability_invocation_id": str(uuid4()),
                "status": "succeeded",
                "attempt": 1,
                "started_at": now,
                "completed_at": now,
            }
        )
    with pytest.raises(ValidationError):
        WorkerResultReport.model_validate(
            {
                "job_id": str(uuid4()),
                "capability_invocation_id": str(uuid4()),
                "status": "failed",
                "result": {
                    "result_type": "google_sheets.append_values.v1",
                    "status": "succeeded",
                    "updated_range": "Reservations!A2:E2",
                    "updated_rows": 1,
                    "deduplicated": False,
                },
                "attempt": 1,
                "started_at": now,
                "completed_at": now,
            }
        )


def test_plan_discriminator_rejects_unknown_plan() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionPlan).validate_python({"plan_type": "http.post_json.v1"})


def test_runtime_capability_forbids_execution_details() -> None:
    with pytest.raises(ValidationError):
        RuntimeCapabilityDefinition.model_validate(
            {
                "semantic_key": "reservation.submit_request",
                "semantic_version": 1,
                "tool_name": "reservation_submit_request",
                "description": "Submit a reservation request",
                "announcement": "I will submit your request now",
                "input_schema": {},
                "spreadsheet_id": "secret-destination",
            }
        )


@pytest.mark.parametrize(
    ("operation", "operands"),
    [
        ("add", ["1", "2"]),
        ("multiply", ["2", "3", "4"]),
        ("subtract", ["5", "2"]),
        ("divide", ["5", "2"]),
        ("percentage", ["200", "15"]),
    ],
)
def test_calculator_request_accepts_supported_operations(
    operation: str, operands: list[str]
) -> None:
    assert CalculatorRequest(operation=operation, operands=operands).operands == operands


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "unknown", "operands": ["1", "2"]},
        {"operation": "add", "operands": ["1"]},
        {"operation": "add", "operands": [str(index) for index in range(11)]},
        {"operation": "subtract", "operands": ["1", "2", "3"]},
        {"operation": "divide", "operands": ["1"]},
        {"operation": "percentage", "operands": ["1", "2", "3"]},
        {"operation": "add", "operands": [1, "2"]},
        {"operation": "add", "operands": ["1", "2"], "extra": True},
    ],
)
def test_calculator_request_rejects_invalid_shape(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CalculatorRequest.model_validate(payload)
