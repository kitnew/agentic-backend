import json
from uuid import UUID, uuid4

import httpx
import pytest
from backend_core.runtime.capabilities.domain import (
    compile_plan,
    enforce_input_constraints,
    normalize_input,
    resolve_capability,
    semantic_result,
    validate_agent_input,
)
from backend_core.runtime.capabilities.execution import project_execution_outcome
from contracts import RuntimeIntegrationMaterial, TenantCapabilityProfile
from job_worker.worker import (
    GoogleSheetsAppendValuesHandler as WorkerGoogleSheetsAppendValuesHandler,
)


class GoogleSheetsAppendValuesHandler(WorkerGoogleSheetsAppendValuesHandler):
    @staticmethod
    async def _access_token(plan, material):
        assert plan.integration_id == material.integration_id
        return "test-token"


def profile(
    *, phone: bool, spreadsheet_id: str, sheet_name: str, mapping: str
) -> TenantCapabilityProfile:
    properties: dict[str, object] = {
        "guest_name": {"type": "string"},
        "check_in": {
            "type": "string",
            "format": "date",
        },
        "check_out": {
            "type": "string",
            "format": "date",
        },
    }
    required = ["guest_name", "check_in", "check_out"]
    if phone:
        properties["phone"] = {
            "type": "string",
        }
        required.insert(1, "phone")
    return TenantCapabilityProfile.model_validate(
        {
            "enabled": True,
            "semantic_version": 1,
            "description": "Submit a reservation request.",
            "announcement": "I will submit your reservation request now.",
            "agent_input_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            "bindings": {
                "guest_name": "guest.name",
                "check_in": "stay.check_in",
                "check_out": "stay.check_out",
                **({"phone": "guest.phone"} if phone else {}),
            },
            "execution": {
                "plan_type": "google_sheets.append_values.v1",
                "mapping_language": "jsonata",
                "mapping_contract_version": 1,
                "mapping_engine": "jsonata-python",
                "mapping_engine_version": "0.7.0",
                "connection_id": str(uuid4()),
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "append_range": "A:G",
                "idempotency": {
                    "lookup_range": "A:A",
                    "operation_id_column_index": 0,
                },
                "request_mapping": mapping,
            },
            }
    )


def plan(
    capability: TenantCapabilityProfile,
    payload: dict[str, object],
    operation_id: UUID,
):
    resolve_capability("reservation.submit_request", capability)
    validate_agent_input(capability.agent_input_schema, payload)
    business = normalize_input(payload, capability.bindings)
    enforce_input_constraints(business, "Europe/Bratislava", capability.input_constraints)
    return compile_plan(
        capability,
        business,
        operation_id=operation_id,
        call_id=uuid4(),
        tool_call_id="tool-call",
        integration_id=capability.execution.connection_id,
        semantic_key="reservation.submit_request",
    )


@pytest.mark.asyncio
async def test_two_tenants_share_the_full_compilation_and_worker_path() -> None:
    rows: dict[str, list[list[object]]] = {"sheet-a": [], "sheet-b": []}

    def transport(request: httpx.Request) -> httpx.Response:
        spreadsheet = next(key for key in rows if key in str(request.url))
        if request.method == "GET":
            return httpx.Response(200, json={"values": rows[spreadsheet]})
        submitted = json.loads(request.content)["values"]
        rows[spreadsheet].extend(submitted)
        row_number = len(rows[spreadsheet])
        return httpx.Response(
            200,
            json={
                "updates": {
                    "updatedRange": f"Reservations!A{row_number}:G{row_number}",
                    "updatedRows": len(submitted),
                }
            },
        )

    tenant_a = profile(
        phone=False,
        spreadsheet_id="sheet-a",
        sheet_name="Reservations",
        mapping='{"rows": [[metadata.operation_id, business.guest.name, business.stay.check_in, business.stay.check_out]]}',
    )
    tenant_b = profile(
        phone=True,
        spreadsheet_id="sheet-b",
        sheet_name="Booking Requests",
        mapping='{"rows": [[metadata.operation_id, business.stay.check_in, business.stay.check_out, business.guest.name, business.guest.phone, "new", "voice_agent"]]}',
    )
    operation_a = UUID("00000000-0000-0000-0000-000000000001")
    operation_b = UUID("00000000-0000-0000-0000-000000000002")
    plan_a = plan(
        tenant_a,
        {"guest_name": "Alice", "check_in": "2026-08-12", "check_out": "2026-08-15"},
        operation_a,
    )
    plan_b = plan(
        tenant_b,
        {
            "guest_name": "Bob",
            "phone": "+421900000000",
            "check_in": "2026-08-20",
            "check_out": "2026-08-22",
        },
        operation_b,
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        handler = GoogleSheetsAppendValuesHandler(client)
        material_a = RuntimeIntegrationMaterial(
            integration_id=plan_a.integration_id,
            provider="google_sheets",
            secret={"service_account": {}},
        )
        material_b = material_a.model_copy(
            update={"integration_id": plan_b.integration_id}
        )
        first_a = await handler.execute(plan_a, material_a)
        duplicate_a = await handler.execute(plan_a, material_a)
        first_b = await handler.execute(plan_b, material_b)

    assert rows["sheet-a"] == [[str(operation_a), "Alice", "2026-08-12", "2026-08-15"]]
    assert rows["sheet-b"] == [
        [
            str(operation_b),
            "2026-08-20",
            "2026-08-22",
            "Bob",
            "+421900000000",
            "new",
            "voice_agent",
        ]
    ]
    assert plan_a.plan_type == plan_b.plan_type
    assert first_a.deduplicated is False
    assert duplicate_a.deduplicated is True
    assert semantic_result(project_execution_outcome(first_a)) == {}
    assert semantic_result(project_execution_outcome(first_b)) == {}
