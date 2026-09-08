from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from contracts import HttpRequestResult, IntegrationJob, WorkerResultReport
from pydantic import ValidationError


def test_target_worker_job_and_result_round_trip() -> None:
    now = datetime.now(UTC)
    execution_id = uuid4()
    job = IntegrationJob(
        job_id=uuid4(),
        capability_invocation_id=uuid4(),
        call_id=uuid4(),
        execution_id=execution_id,
        worker_context={
            "execution_id": str(execution_id),
            "tenant_id": "tenant-a",
            "action": {"key": "reservation.create", "phase": "runtime"},
        },
        tool_args={"guest_name": "Ada"},
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    assert IntegrationJob.model_validate_json(job.model_dump_json()) == job
    assert "execution_plan" not in job.model_dump()
    result = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=job.capability_invocation_id,
        data={"status": "submitted"},
    )
    report = WorkerResultReport(
        job_id=job.job_id,
        capability_invocation_id=job.capability_invocation_id,
        status="succeeded",
        result=result,
        attempt=1,
        started_at=now,
        completed_at=now,
    )
    assert WorkerResultReport.model_validate_json(report.model_dump_json()) == report


def test_worker_job_rejects_snapshot_and_legacy_plan_fields() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        IntegrationJob.model_validate(
            {
                "job_id": str(uuid4()),
                "capability_invocation_id": str(uuid4()),
                "execution_id": str(uuid4()),
                "worker_context": {},
                "tool_args": {},
                "execution_snapshot_id": str(uuid4()),
                "created_at": now,
                "expires_at": now + timedelta(minutes=1),
            }
        )
