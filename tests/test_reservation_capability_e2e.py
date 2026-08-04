import json
from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest
from backend_core.modules.capabilities.domain import (
    compile_plan,
    definition,
    normalize_input,
    semantic_result,
    validate_agent_input,
    validate_agent_schema,
    validate_business_input,
)
from contracts import TenantCapabilityProfile
from job_worker.worker import GoogleSheetsAppendValuesHandler


class Credentials:
    async def access_token(self, reference: str) -> str:
        assert reference in {"tenant-a-sheets", "tenant-b-sheets"}
        return "test-token"


def profile(
    *, phone: bool, spreadsheet_id: str, sheet_name: str, mapping: str
) -> TenantCapabilityProfile:
    properties: dict[str, object] = {
        "guest_name": {"type": "string", "x-canonical-field": "guest.name"},
        "check_in": {
            "type": "string",
            "format": "date",
            "x-canonical-field": "stay.check_in",
        },
        "check_out": {
            "type": "string",
            "format": "date",
            "x-canonical-field": "stay.check_out",
        },
    }
    required = ["guest_name", "check_in", "check_out"]
    fixture: dict[str, object] = {
        "guest_name": "Fixture",
        "check_in": "2030-01-01",
        "check_out": "2030-01-02",
    }
    if phone:
        properties["phone"] = {
            "type": "string",
            "x-canonical-field": "guest.phone",
        }
        required.insert(1, "phone")
        fixture["phone"] = "+421900000000"
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
            "validation_fixtures": [fixture, fixture],
        }
    )


def plan(
    capability: TenantCapabilityProfile,
    payload: dict[str, object],
    operation_id: UUID,
    credential_ref: str,
):
    semantic = definition("reservation.submit_request", 1)
    validate_agent_schema(capability.agent_input_schema, semantic)
    validate_agent_input(capability.agent_input_schema, payload)
    business = validate_business_input(
        normalize_input(capability.agent_input_schema, payload),
        "Europe/Bratislava",
        today=date(2026, 8, 4),
    )
    return compile_plan(
        capability,
        business,
        operation_id=operation_id,
        call_id=uuid4(),
        tool_call_id="tool-call",
        credential_ref=credential_ref,
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
        "tenant-a-sheets",
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
        "tenant-b-sheets",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        handler = GoogleSheetsAppendValuesHandler(Credentials(), client)
        first_a = await handler.execute(plan_a)
        duplicate_a = await handler.execute(plan_a)
        first_b = await handler.execute(plan_b)

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
    assert semantic_result(first_a).status == "request_submitted"
    assert "confirmed" not in semantic_result(first_b).model_dump_json()
